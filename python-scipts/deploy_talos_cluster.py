#!/usr/bin/env python3

import argparse
import paramiko
import subprocess
import time
import sys
import json
import os
import logging
from tabulate import tabulate

def ssh_command(host, command):
    logging.debug(f"Executing SSH command on {host}: {command}")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, username='root')
        stdin, stdout, stderr = ssh.exec_command(command)
        output = stdout.read().decode()
        error = stderr.read().decode()
        ssh.close()
        if error:
            logging.error(f"Error executing command on {host}: {error.strip()}")
            return None
        return output
    except Exception as e:
        logging.error(f"SSH connection failed: {e}")
        return None

def find_next_available_vmid(proxmox_ip):
    output = ssh_command(proxmox_ip, "pvesh get /cluster/nextid")
    if output is None:
        logging.error("Failed to get next available VMID.")
        return None
    return output.strip()

def clone_vm(proxmox_ip, template_vmid, new_vmid, node_name):
    logging.info(f"Cloning VM {template_vmid} to new VM {new_vmid} with name '{node_name}'...")
    command = f"qm clone {template_vmid} {new_vmid} --full --name '{node_name}'"
    output = ssh_command(proxmox_ip, command)
    if output is None:
        logging.error(f"Failed to clone VM {template_vmid} to {new_vmid}")
        return False
    return True

def set_vm_resources(proxmox_ip, vmid, memory, cores):
    logging.info(f"Setting resources for VM {vmid}: Memory={memory}MB, Cores={cores}...")
    command = f"qm set {vmid} --memory {memory} --cores {cores}"
    output = ssh_command(proxmox_ip, command)
    if output is None:
        logging.error(f"Failed to set resources for VM {vmid}")
        return False
    return True

def start_vm(proxmox_ip, vmid):
    logging.info(f"Starting VM {vmid}...")
    command = f"qm start {vmid}"
    output = ssh_command(proxmox_ip, command)
    if output is None:
        logging.error(f"Failed to start VM {vmid}")
        return False
    return True

def stop_vm(proxmox_ip, vmid):
    logging.info(f"Stopping VM {vmid}...")
    command = f"qm stop {vmid}"
    output = ssh_command(proxmox_ip, command)
    if output is None:
        logging.error(f"Failed to stop VM {vmid}")
        return False
    return True

def delete_vm(proxmox_ip, vmid):
    logging.info(f"Deleting VM {vmid}...")
    command = f"qm destroy {vmid} --purge"
    output = ssh_command(proxmox_ip, command)
    if output is None:
        logging.error(f"Failed to delete VM {vmid}")
        return False
    return True

def wait_for_vm(proxmox_ip, vmid):
    logging.info(f"Waiting for VM {vmid} to start...")
    while True:
        status_output = ssh_command(proxmox_ip, f"qm status {vmid}")
        if status_output is None:
            logging.error(f"Failed to get status for VM {vmid}")
            return False
        if "status: running" in status_output:
            logging.info(f"VM {vmid} is running.")
            break
        else:
            logging.info(f"VM {vmid} is not running yet. Waiting 5 seconds...")
            time.sleep(5)
    return True

def get_vm_ip(proxmox_ip, vmid, timeout=600, interval=10):
    logging.info(f"Fetching IP address for VM {vmid}...")
    command = f"qm guest cmd {vmid} network-get-interfaces"
    elapsed_time = 0
    while elapsed_time < timeout:
        output = ssh_command(proxmox_ip, command)
        if output is None:
            logging.info("QEMU guest agent is not running yet or command failed. Waiting...")
        elif "QEMU guest agent is not running" in output:
            logging.info("QEMU guest agent is not running yet. Waiting...")
        else:
            try:
                interfaces = json.loads(output)
                for interface in interfaces:
                    ip_addresses = interface.get("ip-addresses", [])
                    for ip_info in ip_addresses:
                        if ip_info.get("ip-address-type") == "ipv4" and ip_info.get("ip-address") != "127.0.0.1":
                            ip_address = ip_info.get("ip-address")
                            logging.info(f"Found IP address: {ip_address}")
                            return ip_address
                logging.info("No valid IP address found. Waiting...")
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse network interfaces output: {e}. Waiting...")
        time.sleep(interval)
        elapsed_time += interval
    logging.error(f"Failed to retrieve VM IP address within {timeout} seconds.")
    return None

def ping_vm(ip_address):
    logging.info(f"Pinging IP address {ip_address}...")
    try:
        subprocess.run(["ping", "-c", "4", ip_address], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logging.info("Ping successful.")
        return True
    except subprocess.CalledProcessError:
        logging.error(f"Ping to {ip_address} failed.")
        return False

def generate_talos_config(cluster_name, control_plane_ip, output_dir):
    logging.info("Generating Talos configuration...")
    os.makedirs(output_dir, exist_ok=True)
    cluster_endpoint = f"https://{control_plane_ip}:6443"

    command = [
        "talosctl", "gen", "config", cluster_name,
        cluster_endpoint,
        "--output-dir", output_dir,
    ]
    try:
        logging.debug(f"Running command: {' '.join(command)}")
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info("Talos configuration generated successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to generate Talos configuration: {e.stderr.decode().strip()}")
        sys.exit(1)

def apply_talos_config(ip_address, config_file):
    logging.info(f"Applying Talos configuration to node {ip_address}...")
    command = [
        "talosctl", "apply-config", "--insecure",
        "--nodes", ip_address,
        "--file", config_file
    ]
    try:
        logging.debug(f"Running command: {' '.join(command)}")
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info(f"Configuration applied to node {ip_address}.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to apply Talos configuration to node {ip_address}: {e.stderr.decode().strip()}")
        sys.exit(1)

def bootstrap_talos(control_plane_ip, talosconfig):
    logging.info("Bootstrapping Talos control plane...")
    os.environ['TALOSCONFIG'] = talosconfig
    try:
        subprocess.run(["talosctl", "config", "endpoint", control_plane_ip], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["talosctl", "config", "nodes", control_plane_ip], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["talosctl", "bootstrap"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info("Talos control plane bootstrapped successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to bootstrap Talos: {e.stderr.decode().strip()}")
        sys.exit(1)

def generate_kubeconfig(output_dir):
    logging.info("Generating kubeconfig...")
    kubeconfig_path = os.path.join(output_dir, 'kubeconfig')
    command = ["talosctl", "kubeconfig", kubeconfig_path]
    try:
        logging.debug(f"Running command: {' '.join(command)}")
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info("Kubeconfig generated successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to generate kubeconfig: {e.stderr.decode().strip()}")
        sys.exit(1)

def verify_kubernetes_cluster(kubeconfig, expected_node_count, timeout=600, interval=30):
    logging.info("Verifying Kubernetes cluster...")
    elapsed_time = 0
    while elapsed_time < timeout:
        command = ["kubectl", "--kubeconfig", kubeconfig, "get", "nodes", "-o", "json"]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            nodes = json.loads(result.stdout)
            node_count = len(nodes['items'])
            logging.info(f"Found {node_count} nodes in the cluster.")
            if node_count == expected_node_count:
                logging.info("All nodes have joined the cluster.")
                return True
            else:
                logging.info(f"Expected {expected_node_count} nodes, but found {node_count}. Waiting...")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to verify Kubernetes cluster: {e.stderr.strip()}")
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse kubectl output: {e}")
        time.sleep(interval)
        elapsed_time += interval
    logging.error(f"Cluster nodes did not reach expected count of {expected_node_count} within {timeout} seconds.")
    return False

def main():
    # Configure logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description="Deploy a Talos Cluster on Proxmox")
    parser.add_argument("--proxmox-ip", required=True, help="Proxmox server IP address")
    parser.add_argument("--template-vmid", required=True, help="Template VM ID")
    parser.add_argument("--cluster-name", required=True, help="Name of the cluster")
    parser.add_argument("--num-control-planes", type=int, required=True, help="Number of control plane nodes")
    parser.add_argument("--control-plane-ram", type=int, required=True, help="RAM for control plane nodes (in MB)")
    parser.add_argument("--control-plane-cores", type=int, required=True, help="Number of CPU cores for control plane nodes")
    parser.add_argument("--num-workers", type=int, required=True, help="Number of worker nodes")
    parser.add_argument("--worker-ram", type=int, required=True, help="RAM for worker nodes (in MB)")
    parser.add_argument("--worker-cores", type=int, required=True, help="Number of CPU cores for worker nodes")
    parser.add_argument("--output-dir", default="./talos_cluster", help="Output directory for configurations")
    args = parser.parse_args()

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

    cluster_map = {
        "cluster_name": cluster_name,
        "controlplanes": {},
        "workers": {}
    }

    all_vms = []

    try:
        # Step 1: Create VMs for Control Planes
        for i in range(num_control_planes):
            new_vmid = find_next_available_vmid(proxmox_ip)
            if new_vmid is None:
                raise Exception("Could not find an available VMID.")
            node_name = f"{cluster_name}-controlplane-{new_vmid}"
            logging.info(f"Creating control plane node {node_name} with VMID {new_vmid}...")
            if not clone_vm(proxmox_ip, template_vmid, new_vmid, node_name):
                raise Exception(f"Failed to clone control plane VM {new_vmid} with name {node_name}")
            if not set_vm_resources(proxmox_ip, new_vmid, control_plane_ram, control_plane_cores):
                raise Exception(f"Failed to set resources for VM {new_vmid}")
            if not start_vm(proxmox_ip, new_vmid):
                raise Exception(f"Failed to start VM {new_vmid}")
            if not wait_for_vm(proxmox_ip, new_vmid):
                raise Exception(f"VM {new_vmid} did not start properly")
            cluster_map["controlplanes"][node_name] = {
                "vmid": new_vmid,
                "ip": None
            }
            all_vms.append(new_vmid)

        # Step 1: Create VMs for Workers
        for i in range(num_workers):
            new_vmid = find_next_available_vmid(proxmox_ip)
            if new_vmid is None:
                raise Exception("Could not find an available VMID.")
            node_name = f"{cluster_name}-worker-{new_vmid}"
            logging.info(f"Creating worker node {node_name} with VMID {new_vmid}...")
            if not clone_vm(proxmox_ip, template_vmid, new_vmid, node_name):
                raise Exception(f"Failed to clone worker VM {new_vmid}")
            if not set_vm_resources(proxmox_ip, new_vmid, worker_ram, worker_cores):
                raise Exception(f"Failed to set resources for VM {new_vmid}")
            if not start_vm(proxmox_ip, new_vmid):
                raise Exception(f"Failed to start VM {new_vmid}")
            if not wait_for_vm(proxmox_ip, new_vmid):
                raise Exception(f"VM {new_vmid} did not start properly")
            cluster_map["workers"][node_name] = {
                "vmid": new_vmid,
                "ip": None
            }
            all_vms.append(new_vmid)

        # Step 2: Collect IP Addresses for Control Planes
        for node_name, node_info in cluster_map["controlplanes"].items():
            vmid = node_info["vmid"]
            vm_ip = get_vm_ip(proxmox_ip, vmid)
            if vm_ip is None:
                raise Exception(f"Failed to get IP for VM {vmid}")
            if not ping_vm(vm_ip):
                raise Exception(f"Cannot reach VM {vmid} at IP {vm_ip}")
            cluster_map["controlplanes"][node_name]["ip"] = vm_ip

        # Step 2: Collect IP Addresses for Workers
        for node_name, node_info in cluster_map["workers"].items():
            vmid = node_info["vmid"]
            vm_ip = get_vm_ip(proxmox_ip, vmid)
            if vm_ip is None:
                raise Exception(f"Failed to get IP for VM {vmid}")
            if not ping_vm(vm_ip):
                raise Exception(f"Cannot reach VM {vmid} at IP {vm_ip}")
            cluster_map["workers"][node_name]["ip"] = vm_ip

        # Step 3: Generate Talos Configuration
        first_control_plane_ip = next(iter(cluster_map["controlplanes"].values()))["ip"]
        generate_talos_config(cluster_name, first_control_plane_ip, output_dir)
        talosconfig = os.path.join(output_dir, "talosconfig")
        os.environ['TALOSCONFIG'] = talosconfig

        # Step 4: Apply Configuration to Control Planes
        controlplane_config_file = os.path.join(output_dir, "controlplane.yaml")
        for node_name, node_info in cluster_map["controlplanes"].items():
            ip = node_info["ip"]
            apply_talos_config(ip, controlplane_config_file)

        # Step 4: Apply Configuration to Workers
        worker_config_file = os.path.join(output_dir, "worker.yaml")
        for node_name, node_info in cluster_map["workers"].items():
            ip = node_info["ip"]
            apply_talos_config(ip, worker_config_file)

        # Step 5: Bootstrap the Cluster
        logging.info("Waiting for Talos configurations to apply on control plane nodes...")
        time.sleep(120)  # Wait longer to allow nodes to initialize
        bootstrap_talos(first_control_plane_ip, talosconfig)

        # Step 6: Generate Kubeconfig
        generate_kubeconfig(output_dir)
        kubeconfig = os.path.join(output_dir, 'kubeconfig')

        # Step 7: Verify Cluster Health
        expected_node_count = num_control_planes + num_workers
        logging.info("Waiting for the cluster to become healthy...")
        if not verify_kubernetes_cluster(kubeconfig, expected_node_count, timeout=900, interval=30):
            raise Exception("Cluster did not become healthy in the expected time.")

        # Output the cluster map neatly as a table
        logging.info("Cluster deployment completed. Here is the cluster map:")
        controlplane_table = []
        for node_name, node_info in cluster_map["controlplanes"].items():
            controlplane_table.append([node_name, node_info["vmid"], node_info["ip"], "Control Plane"])
        worker_table = []
        for node_name, node_info in cluster_map["workers"].items():
            worker_table.append([node_name, node_info["vmid"], node_info["ip"], "Worker"])
        full_table = controlplane_table + worker_table
        headers = ["Node Name", "VMID", "IP Address", "Role"]
        print(tabulate(full_table, headers=headers, tablefmt="grid"))

        cluster_map_file = os.path.join(output_dir, f"{cluster_name}_cluster_map.json")
        try:
            with open(cluster_map_file, 'w') as f:
                json.dump(cluster_map, f, indent=4)
            logging.info(f"Cluster map saved to {cluster_map_file}")
        except Exception as e:
            logging.error(f"Failed to save cluster map to JSON file: {e}")


        logging.info(f"Talos Cluster '{cluster_name}' setup completed successfully!")

    except Exception as e:
        logging.error(f"An error occurred: {e}")
        logging.info("Initiating cleanup...")
        for vmid in all_vms:
            stop_vm(proxmox_ip, vmid)
            delete_vm(proxmox_ip, vmid)
        logging.info("Cleanup completed. Exiting.")
        sys.exit(1)

if __name__ == "__main__":
    main()

