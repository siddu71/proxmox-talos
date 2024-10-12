#!/usr/bin/env python3

import argparse
import paramiko
import subprocess
import time
import sys
import json
import os
import configparser
import tempfile

def ssh_command(host, command):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, username='root')
        stdin, stdout, stderr = ssh.exec_command(command)
        output = stdout.read().decode()
        error = stderr.read().decode()
        ssh.close()
        if error:
            print(f"Error executing command on {host}: {error.strip()}")
            return None
        return output
    except Exception as e:
        print(f"SSH connection failed: {e}")
        return None

def find_next_available_vmid(proxmox_ip):
    output = ssh_command(proxmox_ip, "pvesh get /cluster/nextid")
    if output is None:
        print("Failed to get next available VMID.")
        return None
    return output.strip()

def clone_vm(proxmox_ip, template_vmid, new_vmid, node_name):
    print(f"Cloning VM {template_vmid} to new VM {new_vmid} with name '{node_name}'...")
    command = f"qm clone {template_vmid} {new_vmid} --full --name '{node_name}'"
    output = ssh_command(proxmox_ip, command)
    if output is None:
        print(f"Failed to clone VM {template_vmid} to {new_vmid}")
        return False
    return True

def set_vm_resources(proxmox_ip, vmid, memory, cores):
    print(f"Setting resources for VM {vmid}: Memory={memory}MB, Cores={cores}...")
    command = f"qm set {vmid} --memory {memory} --cores {cores}"
    output = ssh_command(proxmox_ip, command)
    if output is None:
        print(f"Failed to set resources for VM {vmid}")
        return False
    return True

def start_vm(proxmox_ip, vmid):
    print(f"Starting VM {vmid}...")
    command = f"qm start {vmid}"
    output = ssh_command(proxmox_ip, command)
    if output is None:
        print(f"Failed to start VM {vmid}")
        return False
    return True

def stop_vm(proxmox_ip, vmid):
    print(f"Stopping VM {vmid}...")
    command = f"qm stop {vmid}"
    output = ssh_command(proxmox_ip, command)
    if output is None:
        print(f"Failed to stop VM {vmid}")
        return False
    return True

def delete_vm(proxmox_ip, vmid):
    print(f"Deleting VM {vmid}...")
    command = f"qm destroy {vmid} --purge"
    output = ssh_command(proxmox_ip, command)
    if output is None:
        print(f"Failed to delete VM {vmid}")
        return False
    return True

def wait_for_vm(proxmox_ip, vmid):
    print(f"Waiting for VM {vmid} to start...")
    while True:
        status_output = ssh_command(proxmox_ip, f"qm status {vmid}")
        if status_output is None:
            print(f"Failed to get status for VM {vmid}")
            return False
        if "status: running" in status_output:
            print(f"VM {vmid} is running.")
            break
        else:
            print(f"VM {vmid} is not running yet. Waiting 5 seconds...")
            time.sleep(5)
    return True

def get_vm_ip(proxmox_ip, vmid, timeout=600, interval=10):
    print(f"Fetching IP address for VM {vmid}...")
    command = f"qm guest cmd {vmid} network-get-interfaces"
    elapsed_time = 0
    while elapsed_time < timeout:
        output = ssh_command(proxmox_ip, command)
        if output is None:
            print("QEMU guest agent is not running yet or command failed. Waiting...")
        elif "QEMU guest agent is not running" in output:
            print("QEMU guest agent is not running yet. Waiting...")
        else:
            try:
                interfaces = json.loads(output)
                for interface in interfaces:
                    ip_addresses = interface.get("ip-addresses", [])
                    for ip_info in ip_addresses:
                        if ip_info.get("ip-address-type") == "ipv4" and ip_info.get("ip-address") != "127.0.0.1":
                            ip_address = ip_info.get("ip-address")
                            print(f"Found IP address: {ip_address}")
                            return ip_address
                print("No valid IP address found. Waiting...")
            except json.JSONDecodeError as e:
                print(f"Failed to parse network interfaces output: {e}. Waiting...")
        time.sleep(interval)
        elapsed_time += interval
    print(f"Failed to retrieve VM IP address within {timeout} seconds.")
    return None

def ping_vm(ip_address):
    print(f"Pinging IP address {ip_address}...")
    try:
        subprocess.run(["ping", "-c", "4", ip_address], check=True)
        print("Ping successful.")
        return True
    except subprocess.CalledProcessError:
        print(f"Ping to {ip_address} failed.")
        return False


def generate_talos_secrets(cluster_name, output_dir):
    print("Generating Talos cluster secrets...")
    os.makedirs(output_dir, exist_ok=True)
    command = [
        "talosctl", "gen", "secrets", "--out-dir", output_dir
    ]
    try:
        print(f"Running command: {' '.join(command)}")
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to generate Talos secrets: {e}")
        sys.exit(1)

def generate_node_config(cluster_name, node_ip, node_type, output_dir, secrets_dir):
    print(f"Generating Talos configuration for {node_type} node at {node_ip}...")
    os.makedirs(output_dir, exist_ok=True)
    cluster_endpoint = f"https://{node_ip}:6443" if node_type == "controlplane" else f"https://{control_plane_ips[0]}:6443"


    # Control plane specific patches
    if node_type == "controlplane":
        config_patch_node = [
            {
                "op": "replace",
                "path": "/cluster/controlPlane/endpoint",
                "value": cluster_endpoint
            },
            {
                "op": "replace",
                "path": "/cluster/etcd/initialCluster",
                "value": ",".join([f"{ip}=https://{ip}:2380" for ip in control_plane_ips])
            }
        ]
        config_patches =  config_patch_node

    command = [
        "talosctl", "gen", "config", cluster_name,
        cluster_endpoint,
        "--output-dir", output_dir,
        "--with-secrets", secrets_dir,
        "--config-patch", json.dumps(config_patches),
        "--config-patch-output", os.path.join(output_dir, f"{node_type}-{node_ip}.yaml"),
        "--roles", node_type
    ]
    try:
        print(f"Running command: {' '.join(command)}")
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to generate {node_type} configuration for {node_ip}: {e}")
        sys.exit(1)



def apply_talos_config(ip_address, config_file):
    print(f"Applying Talos configuration to node {ip_address}...")
    command = [
        "talosctl", "apply-config", "--insecure",
        "--nodes", ip_address,
        "--file", config_file
    ]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to apply Talos configuration: {e}")
        sys.exit(1)

def bootstrap_talos(control_plane_ip, talosconfig):
    print("Bootstrapping Talos control plane...")
    os.environ['TALOSCONFIG'] = talosconfig
    try:
        subprocess.run(["talosctl", "config", "endpoint", control_plane_ip], check=True)
        subprocess.run(["talosctl", "config", "node", control_plane_ip], check=True)
        subprocess.run(["talosctl", "bootstrap"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to bootstrap Talos: {e}")
        sys.exit(1)


def generate_kubeconfig(output_dir):
    print("Generating kubeconfig...")
    kubeconfig_path = os.path.join(output_dir, 'kubeconfig')
    command = ["talosctl", "kubeconfig", kubeconfig_path]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to generate kubeconfig: {e}")
        sys.exit(1)


def verify_kubernetes_cluster(kubeconfig):
    print("Verifying Kubernetes cluster...")
    command = ["kubectl", "--kubeconfig", kubeconfig, "get", "nodes"]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to verify Kubernetes cluster: {e}")
        sys.exit(1)

def parse_config_file(config_file):
    config = configparser.ConfigParser()
    config.read(config_file)
    return config['DEFAULT']


def main():
    parser = argparse.ArgumentParser(description="Deploy a Talos Cluster on Proxmox")
    parser.add_argument("--proxmox-ip", help="Proxmox server IP address")
    parser.add_argument("--template-vmid", help="Template VM ID")
    parser.add_argument("--cluster-name", help="Name of the cluster")
    parser.add_argument("--num-control-planes", type=int, help="Number of control plane nodes")
    parser.add_argument("--control-plane-ram", type=int, help="RAM for control plane nodes (in MB)")
    parser.add_argument("--control-plane-cores", type=int, help="Number of CPU cores for control plane nodes")
    parser.add_argument("--num-workers", type=int, help="Number of worker nodes")
    parser.add_argument("--worker-ram", type=int, help="RAM for worker nodes (in MB)")
    parser.add_argument("--worker-cores", type=int, help="Number of CPU cores for worker nodes")
    parser.add_argument("--output-dir", default="./talos_cluster", help="Output directory for configurations")
    parser.add_argument("--config-file", help="Path to configuration file")
    args = parser.parse_args()

    if args.config_file:
        config = parse_config_file(args.config_file)
        proxmox_ip = config.get('proxmox_ip', args.proxmox_ip)
        template_vmid = config.get('template_vmid', args.template_vmid)
        cluster_name = config.get('cluster_name', args.cluster_name)
        num_control_planes = int(config.get('num_control_planes', args.num_control_planes))
        control_plane_ram = int(config.get('control_plane_ram', args.control_plane_ram))
        control_plane_cores = int(config.get('control_plane_cores', args.control_plane_cores))
        num_workers = int(config.get('num_workers', args.num_workers))
        worker_ram = int(config.get('worker_ram', args.worker_ram))
        worker_cores = int(config.get('worker_cores', args.worker_cores))
        output_dir = config.get('output_dir', args.output_dir)
    else:
        proxmox_ip = args.proxmox_ip
        template_vmid = args.template_vmid
        cluster_name = args.cluster_name
        num_control_planes = args.num_control_planes
        control_plane_ram = args.control_plane_ram
        control_plane_cores = args.control_plane_cores
        num_workers = args.num_workers
        worker_ram = args.worker_ram
        worker_cores = args.worker_cores
        output_dir = args.output_dir

    if not all([proxmox_ip, template_vmid, cluster_name, num_control_planes, control_plane_ram, control_plane_cores, num_workers, worker_ram, worker_cores]):
        print("Missing required parameters. Please provide them via command-line arguments or a configuration file.")
        sys.exit(1)

    all_vms = []
    control_plane_ips = []
    worker_ips = []

    try:
        # Deploy Control Plane Nodes
        for i in range(num_control_planes):
            new_vmid = find_next_available_vmid(proxmox_ip)
            if new_vmid is None:
                raise Exception("Could not find an available VMID.")
            node_name = f"talos-controlplane-{new_vmid}"
            print(f"Creating control plane node {node_name} with VMID {new_vmid}...")
            if not clone_vm(proxmox_ip, template_vmid, new_vmid, node_name):
                raise Exception(f"Failed to clone control plane VM {new_vmid}")
            if not set_vm_resources(proxmox_ip, new_vmid, control_plane_ram, control_plane_cores):
                raise Exception(f"Failed to set resources for VM {new_vmid}")
            if not start_vm(proxmox_ip, new_vmid):
                raise Exception(f"Failed to start VM {new_vmid}")
            if not wait_for_vm(proxmox_ip, new_vmid):
                raise Exception(f"VM {new_vmid} did not start properly")
            vm_ip = get_vm_ip(proxmox_ip, new_vmid)
            if vm_ip is None:
                raise Exception(f"Failed to get IP for VM {new_vmid}")
            if not ping_vm(vm_ip):
                raise Exception(f"Cannot reach VM {new_vmid} at IP {vm_ip}")
            control_plane_ips.append(vm_ip)
            all_vms.append(new_vmid)

        # Generate Cluster Secrets
        generate_talos_secrets(cluster_name, output_dir)
        secrets_dir = output_dir

        # Generate and Apply Configurations for Control Plane Nodes
        for ip in control_plane_ips:
            node_output_dir = os.path.join(output_dir, f"controlplane-{ip}")
            generate_node_config(cluster_name, ip, "controlplane", node_output_dir, secrets_dir, control_plane_ips)
            config_file = os.path.join(node_output_dir, f"controlplane-{ip}.yaml")
            apply_talos_config(ip, config_file)

        # Wait and Bootstrap
        print("Waiting for Talos configurations to apply on control plane nodes...")
        time.sleep(60)
        talosconfig = os.path.join(output_dir, "talosconfig")
        os.environ['TALOSCONFIG'] = talosconfig

        # Bootstrap the first control plane node
        bootstrap_talos(control_plane_ips[0], talosconfig)

        # Generate kubeconfig
        generate_kubeconfig(output_dir)
        kubeconfig = os.path.join(output_dir, "kubeconfig")

        # Verify Kubernetes Cluster
        print("Waiting for the cluster to become healthy...")
        time.sleep(60)
        verify_kubernetes_cluster(kubeconfig)
        print(f"Control Plane setup completed with nodes: {control_plane_ips}")

        # Deploy Worker Nodes
        if num_workers > 0:
            for i in range(num_workers):
                new_vmid = find_next_available_vmid(proxmox_ip)
                if new_vmid is None:
                    raise Exception("Could not find an available VMID.")
                node_name = f"talos-worker-{new_vmid}"
                print(f"Creating worker node {node_name} with VMID {new_vmid}...")
                if not clone_vm(proxmox_ip, template_vmid, new_vmid, node_name):
                    raise Exception(f"Failed to clone worker VM {new_vmid}")
                if not set_vm_resources(proxmox_ip, new_vmid, worker_ram, worker_cores):
                    raise Exception(f"Failed to set resources for VM {new_vmid}")
                if not start_vm(proxmox_ip, new_vmid):
                    raise Exception(f"Failed to start VM {new_vmid}")
                if not wait_for_vm(proxmox_ip, new_vmid):
                    raise Exception(f"VM {new_vmid} did not start properly")
                vm_ip = get_vm_ip(proxmox_ip, new_vmid)
                if vm_ip is None:
                    raise Exception(f"Failed to get IP for VM {new_vmid}")
                if not ping_vm(vm_ip):
                    raise Exception(f"Cannot reach VM {new_vmid} at IP {vm_ip}")
                worker_ips.append(vm_ip)
                all_vms.append(new_vmid)

            # Generate and Apply Configurations for Worker Nodes
            for ip in worker_ips:
                node_output_dir = os.path.join(output_dir, f"worker-{ip}")
                generate_node_config(cluster_name, ip, "worker", node_output_dir, secrets_dir, control_plane_ips)
                config_file = os.path.join(node_output_dir, f"worker-{ip}.yaml")
                apply_talos_config(ip, config_file)

            print("Waiting for worker nodes to join the cluster...")
            time.sleep(60)
            verify_kubernetes_cluster(kubeconfig)
            print(f"Worker Nodes setup completed with nodes: {worker_ips}")

        print(f"Talos Cluster '{cluster_name}' setup completed successfully!")
    except Exception as e:
        print(f"An error occurred: {e}")
        print("Initiating cleanup...")
        for vmid in all_vms:
            stop_vm(proxmox_ip, vmid)
            delete_vm(proxmox_ip, vmid)
        print("Cleanup completed. Exiting.")
        sys.exit(1)



if __name__ == "__main__":
    main()

