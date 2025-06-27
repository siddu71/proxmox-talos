#!/usr/bin/env python3

import argparse
import subprocess
import time
import sys
import json
import os
import logging
import proxmox_api as api

def generate_talos_config(cluster_name, control_plane_ip, output_dir):
    logging.info("Generating Talos configuration...")
    os.makedirs(output_dir, exist_ok=True)
    command = [
        "talosctl", "gen", "config", cluster_name,
        f"https://{control_plane_ip}:6443",
        "--output-dir", output_dir
    ]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to generate Talos configuration: {e}")
        sys.exit(1)

def apply_talos_config(ip_address, config_file):
    logging.info(f"Applying Talos configuration to node {ip_address}...")
    command = [
        "talosctl", "apply-config", "--insecure",
        "--nodes", ip_address,
        "--file", config_file
    ]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to apply Talos configuration: {e}")
        sys.exit(1)

def bootstrap_talos(control_plane_ip, talosconfig):
    logging.info("Bootstrapping Talos control plane...")
    os.environ['TALOSCONFIG'] = talosconfig
    try:
        subprocess.run(["talosctl", "config", "endpoint", control_plane_ip], check=True)
        subprocess.run(["talosctl", "config", "node", control_plane_ip], check=True)
        subprocess.run(["talosctl", "bootstrap"], check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to bootstrap Talos: {e}")
        sys.exit(1)

def generate_kubeconfig(output_dir):
    logging.info("Generating kubeconfig...")
    command = ["talosctl", "kubeconfig", os.path.join(output_dir, "kubeconfig")]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to generate kubeconfig: {e}")
        sys.exit(1)

def verify_kubernetes_cluster(kubeconfig):
    logging.info("Verifying Kubernetes cluster...")
    command = ["kubectl", "--kubeconfig", kubeconfig, "get", "nodes"]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to verify Kubernetes cluster: {e}")
        sys.exit(1)

def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
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

    ssh = None
    try:
        ssh = api.connect_to_proxmox(proxmox_ip)
        api.clone_vm(ssh, template_vmid, new_vmid, node_name)
        api.start_vm(ssh, new_vmid)
        api.wait_for_vm(ssh, new_vmid)

        if args.vm_ip:
            vm_ip = args.vm_ip
            logging.info(f"Using provided VM IP address: {vm_ip}")
        else:
            vm_ip = api.get_vm_ip(ssh, new_vmid, timeout=600, interval=10)

        api.ping_vm(vm_ip)

        if node_type == "controlplane":
            generate_talos_config(cluster_name, vm_ip, output_dir)
            controlplane_config_file = os.path.join(output_dir, "controlplane.yaml")
            apply_talos_config(vm_ip, controlplane_config_file)

            logging.info("Waiting for Talos configuration to apply...")
            time.sleep(60)  # Adjust as needed

            talosconfig = os.path.join(output_dir, "talosconfig")
            bootstrap_talos(vm_ip, talosconfig)

            logging.info("Waiting for the cluster to become healthy...")
            time.sleep(60)  # Adjust as needed

            generate_kubeconfig(output_dir)
            kubeconfig = os.path.join(output_dir, "kubeconfig")
            verify_kubernetes_cluster(kubeconfig)

            logging.info(f"Talos Control Plane setup completed in directory {output_dir}!")
        else:
            # For worker nodes, we assume the control plane is already set up
            # and the talosconfig exists in the output directory.
            talosconfig = os.path.join(output_dir, "talosconfig")
            if not os.path.exists(talosconfig):
                logging.error(f"Talos config file {talosconfig} not found. Ensure the control plane is set up and the talosconfig is available.")
                sys.exit(1)

            os.environ['TALOSCONFIG'] = talosconfig

            worker_config_file = os.path.join(output_dir, "worker.yaml")
            if not os.path.exists(worker_config_file):
                logging.info("Generating worker node configuration...")
                # Regenerate the configuration to ensure worker.yaml is present
                generate_talos_config(cluster_name, vm_ip, output_dir)

            apply_talos_config(vm_ip, worker_config_file)

            logging.info("Waiting for worker node to join the cluster...")
            time.sleep(60)  # Adjust as needed

            kubeconfig = os.path.join(output_dir, "kubeconfig")
            verify_kubernetes_cluster(kubeconfig)

            logging.info(f"Talos Worker Node setup completed in directory {output_dir}!")
    finally:
        if ssh and ssh.get_transport() and ssh.get_transport().is_active():
            logging.info("Closing SSH connection.")
            ssh.close()

if __name__ == "__main__":
    main()

