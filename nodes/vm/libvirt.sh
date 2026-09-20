# A BuilderBot node on plain libvirt/KVM: any Linux host with virt-install.
# Run as root, or as a user in the libvirt group with --connect qemu:///system.
#
# Rendered by the dashboard's Create sandbox VM (vmtemplate.py). virt-install
# both defines the machine and starts the installer, so this is the whole of
# it; the disk is created by the same command.
#
# --osinfo wants virt-install 4.0 or newer. On an older one it is
# --os-variant generic, and everything else is the same.
set -eu

BRIDGE=br0                   # the network the node reaches the controller on

virt-install \
  --name ${name} \
  --uuid ${uuid} \
  --machine q35 --boot uefi \
  --vcpus ${cores} --cpu host-passthrough \
  --memory ${memory_mb} \
  --disk path=${disk_path},size=${disk_gb},format=qcow2,bus=virtio,discard=unmap \
  --network bridge=$BRIDGE,model=virtio,mac=${mac} \
  --cdrom ${iso_path} \
  --osinfo detect=on,require=off \
  --graphics none --console pty,target_type=serial \
  --noautoconsole
