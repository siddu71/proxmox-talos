#!/usr/bin/env python3

import argparse
import json
import logging
import sys
import os
import shutil
import proxmox_api as api

def remove_cluster_directory(directory):
    try:
        shutil.rmtree(directory)
        logging.info(f"Successfully removed the directory: {directory}")
    except Exception as e:
        logging.error(f"Failed to remove the directory {directory}: {e}")

def main():
    # Configure logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description="Destroy a Talos Cluster on Proxmox")
    parser.add_argument("--proxmox-ip", required=True, help="Proxmox server IP address")
    parser.add_argument("--cluster-map-file", required=True, help="Path to the cluster map JSON file")
    args = parser.parse_args()

    proxmox_ip = args.proxmox_ip
    cluster_map_file = args.cluster_map_file

    # Load the cluster map from the JSON file
    try:
        with open(cluster_map_file, 'r') as f:
            cluster_map = json.load(f)
        logging.info(f"Loaded cluster map from {cluster_map_file}")
    except Exception as e:
        logging.error(f"Failed to load cluster map: {e}")
        sys.exit(1)

    all_vms = []
    for node_type in ["controlplanes", "workers"]:
        for node_name, node_info in cluster_map[node_type].items():
            vmid = node_info["vmid"]
            all_vms.append(vmid)

    ssh = None
    try:
        ssh = api.connect_to_proxmox(proxmox_ip)
        # Stop and delete VMs
        for vmid in all_vms:
            if not api.stop_vm(ssh, vmid):
                logging.error(f"Failed to stop VM {vmid}. Continuing with next VM.")
                continue
            if not api.delete_vm(ssh, vmid):
                logging.error(f"Failed to delete VM {vmid}. You may need to delete it manually.")
    finally:
        if ssh and ssh.get_transport() and ssh.get_transport().is_active():
            logging.info("Closing SSH connection.")
            ssh.close()

    # Assuming the directory is named after the cluster and stored in the same parent directory as the JSON file
    output_dir = os.path.dirname(cluster_map_file)
    remove_cluster_directory(output_dir)  # Call to remove the directory


    logging.info(f"Cluster '{cluster_map['cluster_name']}' has been destroyed successfully.")

if __name__ == "__main__":
    main()

