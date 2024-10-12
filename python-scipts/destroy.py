#!/usr/bin/env python3

import argparse
import paramiko
import json
import logging
import sys

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

    # Stop and delete VMs
    for vmid in all_vms:
        if not stop_vm(proxmox_ip, vmid):
            logging.error(f"Failed to stop VM {vmid}. Continuing with next VM.")
            continue
        if not delete_vm(proxmox_ip, vmid):
            logging.error(f"Failed to delete VM {vmid}. You may need to delete it manually.")

    logging.info(f"Cluster '{cluster_map['cluster_name']}' has been destroyed successfully.")

if __name__ == "__main__":
    main()

