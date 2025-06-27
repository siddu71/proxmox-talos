import paramiko
import logging
import time
import json
import sys
import getpass
import subprocess

def connect_to_proxmox(proxmox_ip):
    """Establishes a persistent SSH connection to the Proxmox server."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    # Path to your specific private key
    key_filename = '/home/siddu/.ssh/id_ed25519_sidstack'
    
    try:
        logging.info(f"Attempting to connect to {proxmox_ip} using public key: {key_filename}")
        ssh.connect(proxmox_ip, username='root', key_filename=key_filename, timeout=10)
        logging.info("SSH connection successful (public key).")
        return ssh
    except paramiko.AuthenticationException:
        logging.warning("Public key authentication failed.")
        try:
            password = getpass.getpass(f"Enter password for root@{proxmox_ip}: ")
            logging.info("Retrying with password authentication...")
            ssh.connect(proxmox_ip, username='root', password=password, timeout=10)
            logging.info("SSH connection successful (password).")
            return ssh
        except Exception as e:
            logging.error(f"SSH connection failed with password: {e}")
            sys.exit(1)
    except Exception as e:
        logging.error(f"An SSH error occurred: {e}")
        sys.exit(1)

def ssh_command(ssh_client, command):
    """Executes a command on a remote host using an existing Paramiko SSH client."""
    logging.debug(f"Executing SSH command: {command}")
    try:
        stdin, stdout, stderr = ssh_client.exec_command(command)
        output = stdout.read().decode()
        error = stderr.read().decode()
        if error:
            # Don't log expected "not running" errors as failures
            if "QEMU guest agent is not running" not in error:
                logging.error(f"Error executing command: {error.strip()}")
            return error # Return error to be handled by the caller
        return output
    except Exception as e:
        logging.error(f"SSH command execution failed: {e}")
        return None

def find_next_available_vmid(ssh_client):
    output = ssh_command(ssh_client, "pvesh get /cluster/nextid")
    if output is None:
        logging.error("Failed to get next available VMID.")
        return None
    return output.strip()

def clone_vm(ssh_client, template_vmid, new_vmid, node_name):
    logging.info(f"Cloning VM {template_vmid} to new VM {new_vmid} with name '{node_name}'...")
    command = f"qm clone {template_vmid} {new_vmid} --full --name '{node_name}'"
    output = ssh_command(ssh_client, command)
    if output is None or "error" in output.lower():
        logging.error(f"Failed to clone VM {template_vmid} to {new_vmid}")
        return False
    return True

def set_vm_resources(ssh_client, vmid, memory, cores):
    logging.info(f"Setting resources for VM {vmid}: Memory={memory}MB, Cores={cores}...")
    command = f"qm set {vmid} --memory {memory} --cores {cores}"
    output = ssh_command(ssh_client, command)
    if output is None or "error" in output.lower():
        logging.error(f"Failed to set resources for VM {vmid}")
        return False
    return True

def start_vm(ssh_client, vmid):
    logging.info(f"Starting VM {vmid}...")
    command = f"qm start {vmid}"
    output = ssh_command(ssh_client, command)
    if output is None or "error" in output.lower():
        logging.error(f"Failed to start VM {vmid}")
        return False
    return True

def stop_vm(ssh_client, vmid):
    logging.info(f"Stopping VM {vmid}...")
    command = f"qm stop {vmid}"
    output = ssh_command(ssh_client, command)
    if output is None or "error" in output.lower():
        logging.error(f"Failed to stop VM {vmid}")
        return False
    return True

def delete_vm(ssh_client, vmid):
    logging.info(f"Deleting VM {vmid}...")
    command = f"qm destroy {vmid} --purge"
    output = ssh_command(ssh_client, command)
    if output is None or "error" in output.lower():
        logging.error(f"Failed to delete VM {vmid}")
        return False
    return True

def wait_for_vm(ssh_client, vmid):
    logging.info(f"Waiting for VM {vmid} to start...")
    while True:
        status_output = ssh_command(ssh_client, f"qm status {vmid}")
        if status_output is None:
            logging.error(f"Failed to get status for VM {vmid}")
            return False
        if "status: running" in status_output:
            logging.info(f"VM {vmid} is running.")
            break
        else:
            logging.info(f"VM {vmid} is not running yet. Waiting 5 seconds...")
            time.sleep(5)
    return True

def get_vm_ip(ssh_client, vmid, timeout=600, interval=10):
    logging.info(f"Fetching IP address for VM {vmid}...")
    command = f"qm guest cmd {vmid} network-get-interfaces"
    elapsed_time = 0
    while elapsed_time < timeout:
        output = ssh_command(ssh_client, command)
        if output is None:
            logging.info("Command to get IP failed. Waiting...")
        elif "QEMU guest agent is not running" in output:
            logging.info("QEMU guest agent is not running yet. Waiting...")
        else:
            try:
                interfaces = json.loads(output)
                for interface in interfaces:
                    ip_addresses = interface.get("ip-addresses", [])
                    for ip_info in ip_addresses:
                        if ip_info.get("ip-address-type") == "ipv4" and ip_info.get("ip-address") != "127.0.0.1":
                            ip_address = ip_info.get("ip-address")
                            logging.info(f"Found IP address: {ip_address}")
                            return ip_address
                logging.info("No valid IP address found. Waiting...")
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse network interfaces output: {e}. Waiting...")
        time.sleep(interval)
        elapsed_time += interval
    logging.error(f"Failed to retrieve VM IP address within {timeout} seconds.")
    return None

def ping_vm(ip_address):
    logging.info(f"Pinging IP address {ip_address}...")
    try:
        subprocess.run(["ping", "-c", "4", ip_address], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logging.info("Ping successful.")
        return True
    except subprocess.CalledProcessError:
        logging.error(f"Ping to {ip_address} failed.")
        return False