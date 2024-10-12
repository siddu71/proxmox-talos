#!/bin/bash

# Prompt for template VM ID and new VM ID
echo "Enter the template VM ID:"
read TEMPLATE_VMID

echo "Enter the new VM ID:"
read NEW_VMID

echo "Enter Cluster Name:"
read clustername


# Define a unique output directory based on VM ID
OUTPUT_DIR="./$clustername"
mkdir -p $OUTPUT_DIR

# Clone the VM from the template with suppressed output and a unique name
ssh root@192.168.137.56 "qm clone $TEMPLATE_VMID $NEW_VMID --full --name 'talos-controlplane-$NEW_VMID'" > /dev/null

# Start the VM
ssh root@192.168.137.56 "qm start $NEW_VMID"

# Wait for VM to start up and stabilize
echo "Waiting for VM to start and stabilize..."
sleep 60

# Get the IP address of the new VM
CONTROL_PLANE_IP=$(ssh root@192.168.137.56 "qm guest cmd $NEW_VMID network-get-interfaces" | yq e '.[] | select(.["ip-addresses"][]) | .["ip-addresses"][] | select(.["ip-address-type"]=="ipv4" and .["ip-address"] != "127.0.0.1").["ip-address"]' -)

echo "Detected Control Plane IP: $CONTROL_PLANE_IP"

# Test ping to the new VM
ping -c 4 $CONTROL_PLANE_IP

# Generate Talos configuration
talosctl gen config talos-proxmox-cluster "https://$CONTROL_PLANE_IP:6443" --output-dir $OUTPUT_DIR

# Apply the Talos configuration
talosctl apply-config --insecure --nodes $CONTROL_PLANE_IP --file $OUTPUT_DIR/controlplane.yaml

# Wait for the configuration to take effect
echo "Waiting for Talos configuration to apply..."
sleep 60

# Set Talos config endpoint and node
export TALOSCONFIG="$OUTPUT_DIR/talosconfig"
talosctl config endpoint $CONTROL_PLANE_IP
talosctl config node $CONTROL_PLANE_IP

# Bootstrap the Talos control plane
talosctl bootstrap

# Wait for cluster components to become healthy
echo "Waiting for the cluster to become healthy..."
sleep 60

# Generate and verify kubeconfig
talosctl kubeconfig $OUTPUT_DIR/kubeconfig

# Verify Kubernetes cluster creation
kubectl --kubeconfig $OUTPUT_DIR/kubeconfig get nodes

echo "Talos Control Plane setup completed in directory $OUTPUT_DIR!"

