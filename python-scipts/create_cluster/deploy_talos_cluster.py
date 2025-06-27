#!/usr/bin/env python3
import argparse
import subprocess
import time
import sys
import json
import os
import logging
from tabulate import tabulate
import proxmox_api as api

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
    parser.add_argument("--output-path", default="./talos_clusters", help="Base path for output directories")
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
    base_output_path = args.output_path

    # --- New Directory Structure Definition ---
    cluster_root_dir = os.path.join(base_output_path, cluster_name)
    talos_config_dir = os.path.join(cluster_root_dir, "talos-config")
    kubeconfig_dir = os.path.join(cluster_root_dir, "kubeconfig")
    # For future FluxCD GitOps structure
    bootstrap_dir = os.path.join(cluster_root_dir, "bootstrap", "helm-charts")
    kustomize_dir = os.path.join(cluster_root_dir, "kustomize", "base")

    # Create all directories
    dirs_to_create = [
        cluster_root_dir,
        talos_config_dir,
        kubeconfig_dir,
        bootstrap_dir,
        kustomize_dir
    ]
    for d in dirs_to_create:
        os.makedirs(d, exist_ok=True)

    logging.info(f"Cluster root directory for '{cluster_name}' is set to: {cluster_root_dir}")

    cluster_map = {
        "cluster_name": cluster_name,
        "controlplanes": {},
        "workers": {}
    }
    all_vms = []
    ssh = None
    try:
        # Step 0: Establish a persistent SSH connection
        ssh = api.connect_to_proxmox(proxmox_ip)

        # Main deployment logic starts here
        try:
            # Step 1: Create VMs for Control Planes
            for i in range(num_control_planes):
                new_vmid = api.find_next_available_vmid(ssh)
                if new_vmid is None: raise Exception("Could not find an available VMID.")
                node_name = f"{cluster_name}-controlplane-{new_vmid}"
                logging.info(f"Creating control plane node {node_name} with VMID {new_vmid}...")
                if not api.clone_vm(ssh, template_vmid, new_vmid, node_name): raise Exception(f"Failed to clone control plane VM {new_vmid} with name {node_name}")
                if not api.set_vm_resources(ssh, new_vmid, control_plane_ram, control_plane_cores): raise Exception(f"Failed to set resources for VM {new_vmid}")
                if not api.start_vm(ssh, new_vmid): raise Exception(f"Failed to start VM {new_vmid}")
                if not api.wait_for_vm(ssh, new_vmid): raise Exception(f"VM {new_vmid} did not start properly")
                cluster_map["controlplanes"][node_name] = {"vmid": new_vmid, "ip": None}
                all_vms.append(new_vmid)
            # Step 1: Create VMs for Workers
            for i in range(num_workers):
                new_vmid = api.find_next_available_vmid(ssh)
                if new_vmid is None: raise Exception("Could not find an available VMID.")
                node_name = f"{cluster_name}-worker-{new_vmid}"
                logging.info(f"Creating worker node {node_name} with VMID {new_vmid}...")
                if not api.clone_vm(ssh, template_vmid, new_vmid, node_name): raise Exception(f"Failed to clone worker VM {new_vmid}")
                if not api.set_vm_resources(ssh, new_vmid, worker_ram, worker_cores): raise Exception(f"Failed to set resources for VM {new_vmid}")
                if not api.start_vm(ssh, new_vmid): raise Exception(f"Failed to start VM {new_vmid}")
                if not api.wait_for_vm(ssh, new_vmid): raise Exception(f"VM {new_vmid} did not start properly")
                cluster_map["workers"][node_name] = {"vmid": new_vmid, "ip": None}
                all_vms.append(new_vmid)
            # Step 2: Collect IP Addresses for all nodes
            for node_type, nodes in [("controlplanes", cluster_map["controlplanes"]), ("workers", cluster_map["workers"])]:
                for node_name, node_info in nodes.items():
                    vmid = node_info["vmid"]
                    vm_ip = api.get_vm_ip(ssh, vmid)
                    if vm_ip is None: raise Exception(f"Failed to get IP for VM {vmid}")
                    if not api.ping_vm(vm_ip): raise Exception(f"Cannot reach VM {vmid} at IP {vm_ip}")
                    cluster_map[node_type][node_name]["ip"] = vm_ip

            # Step 3: Generate Talos Configuration
            first_control_plane_ip = next(iter(cluster_map["controlplanes"].values()))["ip"]
            generate_talos_config(cluster_name, first_control_plane_ip, talos_config_dir)
            talosconfig = os.path.join(talos_config_dir, "talosconfig")
            os.environ['TALOSCONFIG'] = talosconfig

            # Step 4: Apply Configuration to Nodes
            controlplane_config_file = os.path.join(talos_config_dir, "controlplane.yaml")
            for node_info in cluster_map["controlplanes"].values():
                apply_talos_config(node_info["ip"], controlplane_config_file)
            worker_config_file = os.path.join(talos_config_dir, "worker.yaml")
            for node_info in cluster_map["workers"].values():
                apply_talos_config(node_info["ip"], worker_config_file)

            # Step 5: Bootstrap the Cluster
            logging.info("Waiting for Talos configurations to apply on control plane nodes...")
            time.sleep(120)
            bootstrap_talos(first_control_plane_ip, talosconfig)

            # Step 6: Generate Kubeconfig
            generate_kubeconfig(kubeconfig_dir)
            kubeconfig = os.path.join(kubeconfig_dir, 'kubeconfig')

            # Step 7: Verify Cluster Health
            expected_node_count = num_control_planes + num_workers
            logging.info("Waiting for the cluster to become healthy...")
            if not verify_kubernetes_cluster(kubeconfig, expected_node_count, timeout=900, interval=30):
                raise Exception("Cluster did not become healthy in the expected time.")

            # Output the cluster map neatly as a table
            logging.info("Cluster deployment completed. Here is the cluster map:")
            controlplane_table = [[name, info["vmid"], info["ip"], "Control Plane"] for name, info in cluster_map["controlplanes"].items()]
            worker_table = [[name, info["vmid"], info["ip"], "Worker"] for name, info in cluster_map["workers"].items()]
            full_table = controlplane_table + worker_table
            headers = ["Node Name", "VMID", "IP Address", "Role"]
            print(tabulate(full_table, headers=headers, tablefmt="grid"))

            cluster_map_file = os.path.join(talos_config_dir, f"{cluster_name}_cluster_map.json")
            with open(cluster_map_file, 'w') as f:
                json.dump(cluster_map, f, indent=4)
            logging.info(f"Cluster map saved to {cluster_map_file}")
            logging.info(f"Kubeconfig available at: {kubeconfig}")
            logging.info(f"Talos Cluster '{cluster_name}' setup completed successfully!")

        except Exception as e:
            logging.error(f"An error occurred during deployment: {e}")
            logging.info("Initiating cleanup...")
            for vmid in all_vms:
                api.stop_vm(ssh, vmid)
                api.delete_vm(ssh, vmid)
            logging.info("Cleanup completed. Exiting.")
            sys.exit(1)
    finally:
        # Ensure the SSH connection is closed when the script exits
        if ssh and ssh.get_transport() and ssh.get_transport().is_active():
            logging.info("Closing SSH connection.")
            ssh.close()

if __name__ == "__main__":
    main()
