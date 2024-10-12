# Deploy Talos Cluster on Proxmox

This Python script automates the deployment of a Talos cluster on Proxmox virtual environment. It handles the creation, configuration, and management of virtual machines (VMs), generating necessary Talos configurations, and setting up a Kubernetes cluster.

## Prerequisites

Before you begin, ensure you have the following installed:
- Python 3
- `paramiko` for SSH operations
- `subprocess` and `json` for processing commands and outputs
- `tabulate` for formatting output tables

Additionally, you will need:
- Access credentials to a Proxmox server with rights to manage VMs.
- A template VM ID in Proxmox to clone for creating new VMs.

## Installation

1. Clone the repository or download the script to your local machine.
2. Install required Python packages:
   ```bash
   pip install paramiko tabulate
   ```

## Configuration

Configure your Proxmox and cluster settings in the script or pass them as arguments when running the script.

## Usage

Run the script with the required parameters. Here's how to use the command-line interface:

```bash
python deploy_talos_cluster.py --proxmox-ip [PROXMOX_IP] \
                               --template-vmid [TEMPLATE_VMID] \
                               --cluster-name [CLUSTER_NAME] \
                               --num-control-planes [NUM_CONTROL_PLANES] \
                               --control-plane-ram [CONTROL_PLANE_RAM_MB] \
                               --control-plane-cores [CONTROL_PLANE_CORES] \
                               --num-workers [NUM_WORKERS] \
                               --worker-ram [WORKER_RAM_MB] \
                               --worker-cores [WORKER_CORES] \
                               --output-path [OUTPUT_PATH]
```

### Parameters

- `--proxmox-ip`: IP address of the Proxmox server.
- `--template-vmid`: VMID of the Proxmox VM template to clone.
- `--cluster-name`: Desired name of the Talos cluster.
- `--num-control-planes`: Number of control plane nodes.
- `--control-plane-ram`: RAM in MB for each control plane node.
- `--control-plane-cores`: Number of CPU cores for each control plane node.
- `--num-workers`: Number of worker nodes.
- `--worker-ram`: RAM in MB for each worker node.
- `--worker-cores`: Number of CPU cores for each worker node.
- `--output-path`: Base path for output directories; the script will create a subdirectory with the cluster name.

## Output

The script will:
- Create VMs based on the specified template.
- Configure VMs with the specified resources.
- Start and verify VMs.
- Set up Talos and Kubernetes configurations.
- Print a tabulated list of nodes with their details.

Upon successful execution, the script outputs the configuration and state of the deployed cluster in a structured table format.

## Cleanup

If there is an error during deployment, the script will attempt to clean up by stopping and deleting any VMs it created.

## Example

```bash
python deploy_talos_cluster.py --proxmox-ip 192.168.1.100 \
                               --template-vmid 100 \
                               --cluster-name mycluster \
                               --num-control-planes 3 \
                               --control-plane-ram 4096 \
                               --control-plane-cores 2 \
                               --num-workers 2 \
                               --worker-ram 2048 \
                               --worker-cores 1 \
                               --output-path ./clusters
```

This will deploy a cluster named `mycluster` with 3 control planes and 2 worker nodes on the specified Proxmox server.

