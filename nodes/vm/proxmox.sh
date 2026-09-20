# A BuilderBot node on Proxmox VE. Run on the PVE host, as root.
#
# Rendered by the dashboard's Create sandbox VM (vmtemplate.py); the id, the
# uuid and the MAC are this machine's. Proxmox mints its own uuid when it
# makes a VM; passing one here means the machine keeps its identity if the
# config is ever recreated from this file.
#
# Two names to check before running: the storage the disks land on (local-lvm
# on a stock install, or your ZFS/thin pool) and the bridge (vmbr0).
set -eu

STORAGE=local-lvm            # where the disks go
ISOSTORE=local               # where the installer image is
BRIDGE=vmbr0                 # the network the node reaches the controller on

qm create ${vmid} \
  --name ${name} \
  --ostype l26 --machine q35 --bios ovmf \
  --smbios1 uuid=${uuid} \
  --cores ${cores} --cpu host --numa 0 \
  --memory ${memory_mb} --balloon 0 \
  --scsihw virtio-scsi-single \
  --efidisk0 "$STORAGE:1,efitype=4m,pre-enrolled-keys=0" \
  --scsi0 "$STORAGE:${disk_gb},discard=on,ssd=1,iothread=1" \
  --ide2 "$ISOSTORE:iso/${iso},media=cdrom" \
  --boot 'order=scsi0;ide2' \
  --net0 "virtio=${mac},bridge=$BRIDGE" \
  --agent enabled=1 \
  --serial0 socket

qm start ${vmid}
