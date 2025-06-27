# Proxmox Talos Cluster Automation

This project provides a set of Python scripts to automate the deployment of Talos Kubernetes clusters on Proxmox.

## Why use this over Terraform?

*   **Simplicity:** This tool is designed to be the easiest way to get a Talos cluster running on Proxmox.
*   **Golden Image Workflow:** It leverages a pre-configured Proxmox VM template (a "golden image") to ensure that cluster nodes are created quickly and consistently. This avoids the complexity of trying to configure a VM from scratch using Infrastructure as Code.

## Getting Started

### Prerequisites

*   Python 3
*   `talosctl`
*   `kubectl`

### Installation

```bash
pip install -r python-scipts/requirements.txt
```

### Usage

(Coming soon)

## Project Structure

*   `python-scipts/`: The core Python scripts for managing clusters.
    *   `create_cluster/`: Scripts for creating a new cluster.
    *   `create_node/`: Scripts for adding nodes to an existing cluster.
    *   `destroy/`: Scripts for destroying a cluster.
*   `archive/`: Deprecated bash scripts.

## Contributing

(Coming soon)