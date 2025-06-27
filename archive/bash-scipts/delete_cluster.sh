#!/bin/bash

# Check if any VM ID is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <vmid1> <vmid2> <vmid3> ..."
    exit 1
fi

# Loop through all provided VM IDs
for vmid in "$@"
do
    echo "Processing VM ID: $vmid"

    # Check if the VM exists and the guest agent is reachable
    if ! ssh root@192.168.137.56 "qm guest cmd $vmid ping" > /dev/null 2>&1; then
        echo "VM ID $vmid does not exist or guest agent is not reachable. Skipping..."
        continue
    fi

    # Shutdown the VM gracefully
    echo "Shutting down VM ID $vmid..."
    ssh root@192.168.137.56 "qm guest cmd $vmid shutdown" && sleep 30

    # Force stop the VM if it's still running
    vm_status=$(ssh root@192.168.137.56 "qm guest cmd $vmid get-osinfo" 2>&1)
    if [[ "$vm_status" != *"VM $vmid not running"* ]]; then
        echo "Force stopping VM ID $vmid..."
        ssh root@192.168.137.56 "qm stop $vmid"
    fi

    # Delete the VM
    echo "Deleting VM ID $vmid..."
    ssh root@192.168.137.56 "qm destroy $vmid"

    echo "VM ID $vmid has been deleted."
done

echo "All specified VMs have been processed."

