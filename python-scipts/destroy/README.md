# Destroy Talos Cluster on Proxmox

This Python script automates the process of stopping and deleting virtual machines associated with a Talos cluster on Proxmox, as well as cleaning up related directories.

## Prerequisites

Before you can use this script, you need:
- Python 3
- `paramiko` for SSH communication
- Access to a Proxmox server with rights to manage VMs

## Installation

1. Ensure Python 3 is installed on your machine.
2. Install the `paramiko` library using pip:
   ```bash
   pip install paramiko
   ```

## Configuration

The script uses an external JSON file to retrieve the cluster map, which contains information about the VMs to be destroyed. Make sure this file is accurate and up-to-date.

## Usage

Run the script from the command line, providing the necessary parameters:

```bash
python destroy_talos_cluster.py --proxmox-ip [PROXMOX_IP] --cluster-map-file [PATH_TO_CLUSTER_MAP]
```

### Parameters

- `--proxmox-ip`: The IP address of the Proxmox server.
- `--cluster-map-file`: The path to the JSON file containing the cluster map.

## How It Works

1. The script reads the VM IDs from the provided cluster map JSON file.
2. It attempts to stop and then delete each VM listed in the cluster map.
3. After managing the VMs, the script removes the directory specified in the cluster map, assuming it contains configuration files or other data related to the cluster.

## Example

Here is an example of how to run the script:

```bash
python destroy_talos_cluster.py --proxmox-ip 192.168.1.100 --cluster-map-file ./path/to/cluster_map.json
```

## Cleanup

The script performs cleanup automatically after the cluster is destroyed, removing the directory where the cluster configurations were stored.

## Troubleshooting

If a VM fails to stop or delete, you may need to manually intervene via the Proxmox GUI or CLI. Ensure your user account has adequate permissions.

