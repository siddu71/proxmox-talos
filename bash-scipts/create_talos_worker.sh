#!/bin/bash

# Prompt for template VM ID and new VM ID
echo "Enter the template VM ID:"
read TEMPLATE_VMID

echo "Enter the new VM ID:"
read NEW_VMID

echo "Enter Cluster name:"
read clustername


# Clone the VM from the template with suppressed output and a unique name
ssh root@192.168.137.56 "qm clone $TEMPLATE_VMID $NEW_VMID --full --name 'talos-worker-$NEW_VMID'" > /dev/null

# Start the VM
ssh root@192.168.137.56 "qm start $NEW_VMID"

# Wait for VM to start up and stabilize
echo "Waiting for VM to start and stabilize..."
sleep 60

# Get the IP address of the new VM
WORKER_IP=$(ssh root@192.168.137.56 "qm guest cmd $NEW_VMID network-get-interfaces" | yq e '.[] | select(.["ip-addresses"][]) | .["ip-addresses"][] | select(.["ip-address-type"]=="ipv4" and .["ip-address"] != "127.0.0.1").["ip-address"]' -)

echo "Detected Control Plane IP: $WORKER_IP"

# Test ping to the new VM
ping -c 4 $WORKER_IP

# Generate Talos configuration
talosctl gen config talos-proxmox-cluster "https://$WORKER_IP:6443" --output-dir $OUTPUT_DIR

# Apply the Talos configuration
talosctl apply-config --insecure --nodes $WORKER_IP --file $clustername/worker.yaml

#verify if it joined the cluster using kubectl
#TD
echo "Talos Control Plane setup completed in directory $OUTPUT_DIR!"

