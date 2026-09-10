# A BuilderBot node on VirtualBox. Run as the user the VMs belong to.
#
# Rendered by the dashboard's Create sandbox VM (vmtemplate.py). VirtualBox
# takes a MAC without separators, from its own range (08:00:27:xx:xx:xx), and
# a disk size in megabytes.
#
# --bridgeadapter1 is the host interface the node reaches the controller on;
# `VBoxManage list bridgedifs` names them.
set -eu

BRIDGE=eth0

VBoxManage createvm --name "${name}" --uuid ${uuid} --ostype Ubuntu_64 --register
VBoxManage modifyvm "${name}" \
  --cpus ${cores} --memory ${memory_mb} --firmware efi \
  --nic1 bridged --bridgeadapter1 "$BRIDGE" --nictype1 virtio \
  --macaddress1 ${mac_plain} \
  --graphicscontroller vmsvga --audio-driver none --rtcuseutc on
VBoxManage createmedium disk --filename "${disk_path}" --size ${disk_mb} --format VDI
VBoxManage storagectl "${name}" --name SATA --add sata --controller IntelAhci --portcount 2
VBoxManage storageattach "${name}" --storagectl SATA --port 0 --device 0 \
  --type hdd --medium "${disk_path}" --discard on
VBoxManage storageattach "${name}" --storagectl SATA --port 1 --device 0 \
  --type dvddrive --medium "${iso_path}"
VBoxManage startvm "${name}" --type headless
