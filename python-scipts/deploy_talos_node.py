#!/usr/bin/env python3

import argparse
import paramiko
import subprocess
import time
import sys
import json
import os

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
        sys.exit(1)

def clone_vm(proxmox_ip, template_vmid, new_vmid, node_name):
    print(f"Cloning VM {template_vmid} to new VM {new_vmid} with name '{node_name}'...")
    command = f"qm clone {template_vmid} {new_vmid} --full --name '{node_name}'"
    output = ssh_command(proxmox_ip, command)
    if output is None:
        print(f"Failed to clone VM {template_vmid} to {new_vmid}")
        sys.exit(1)

def start_vm(proxmox_ip, vmid):
    print(f"Starting VM {vmid}...")
    command = f"qm start {vmid}"
    output = ssh_command(proxmox_ip, command)
    if output is None:
        print(f"Failed to start VM {vmid}")
        sys.exit(1)

def wait_for_vm(proxmox_ip, vmid):
    print(f"Waiting for VM {vmid} to start...")
    while True:
        status_output = ssh_command(proxmox_ip, f"qm status {vmid}")
        if status_output is None:
            print(f"Failed to get status for VM {vmid}")
            sys.exit(1)
        if "status: running" in status_output:
            print(f"VM {vmid} is running.")
            break
        else:
            print(f"VM {vmid} is not running yet. Waiting 5 seconds...")
            time.sleep(5)

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
    sys.exit(1)

def ping_vm(ip_address):
    print(f"Pinging IP address {ip_address}...")
    try:
        subprocess.run(["ping", "-c", "4", ip_address], check=True)
        print("Ping successful.")
    except subprocess.CalledProcessError:
        print(f"Ping to {ip_address} failed.")
        sys.exit(1)

def generate_talos_config(cluster_name, control_plane_ip, output_dir):
    print("Generating Talos configuration...")
    os.makedirs(output_dir, exist_ok=True)
    command = [
        "talosctl", "gen", "config", cluster_name,
        f"https://{control_plane_ip}:6443",
        "--output-dir", output_dir
    ]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to generate Talos configuration: {e}")
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
    command = ["talosctl", "kubeconfig", os.path.join(output_dir, "kubeconfig")]
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

def main():
    parser = argparse.ArgumentParser(description="Deploy Talos Nodes on Proxmox")
    parser.add_argument("--proxmox-ip", required=True, help="Proxmox server IP address")
    parser.add_argument("--template-vmid", required=True, help="Template VM ID")
    parser.add_argument("--new-vmid", required=True, help="New VM ID")
    parser.add_argument("--node-type", choices=["controlplane", "worker"], required=True, help="Type of node to create")
    parser.add_argument("--cluster-name", required=True, help="Name of the cluster")
    parser.add_argument("--output-dir", default="./talos_cluster", help="Output directory for configurations")
    parser.add_argument("--vm-ip", help="IP address to assign to the new VM (optional)")
    args = parser.parse_args()

    proxmox_ip = args.proxmox_ip
    template_vmid = args.template_vmid
    new_vmid = args.new_vmid
    node_type = args.node_type
    cluster_name = args.cluster_name
    output_dir = args.output_dir

    node_name = f"talos-{node_type}-{new_vmid}"

    clone_vm(proxmox_ip, template_vmid, new_vmid, node_name)
    start_vm(proxmox_ip, new_vmid)
    wait_for_vm(proxmox_ip, new_vmid)

    if args.vm_ip:
        vm_ip = args.vm_ip
        print(f"Using provided VM IP address: {vm_ip}")
    else:
        vm_ip = get_vm_ip(proxmox_ip, new_vmid, timeout=600, interval=10)

    ping_vm(vm_ip)

    if node_type == "controlplane":
        generate_talos_config(cluster_name, vm_ip, output_dir)
        controlplane_config_file = os.path.join(output_dir, "controlplane.yaml")
        apply_talos_config(vm_ip, controlplane_config_file)

        print("Waiting for Talos configuration to apply...")
        time.sleep(60)  # Adjust as needed

        talosconfig = os.path.join(output_dir, "talosconfig")
        bootstrap_talos(vm_ip, talosconfig)

        print("Waiting for the cluster to become healthy...")
        time.sleep(60)  # Adjust as needed

        generate_kubeconfig(output_dir)
        kubeconfig = os.path.join(output_dir, "kubeconfig")
        verify_kubernetes_cluster(kubeconfig)

        print(f"Talos Control Plane setup completed in directory {output_dir}!")
    else:
        # For worker nodes, we assume the control plane is already set up
        # and the talosconfig exists in the output directory.
        talosconfig = os.path.join(output_dir, "talosconfig")
        if not os.path.exists(talosconfig):
            print(f"Talos config file {talosconfig} not found. Ensure the control plane is set up and the talosconfig is available.")
            sys.exit(1)

        os.environ['TALOSCONFIG'] = talosconfig

        worker_config_file = os.path.join(output_dir, "worker.yaml")
        if not os.path.exists(worker_config_file):
            print("Generating worker node configuration...")
            # Regenerate the configuration to ensure worker.yaml is present
            generate_talos_config(cluster_name, vm_ip, output_dir)

        apply_talos_config(vm_ip, worker_config_file)

        print("Waiting for worker node to join the cluster...")
        time.sleep(60)  # Adjust as needed

        kubeconfig = os.path.join(output_dir, "kubeconfig")
        verify_kubernetes_cluster(kubeconfig)

        print(f"Talos Worker Node setup completed in directory {output_dir}!")

if __name__ == "__main__":
    main()

