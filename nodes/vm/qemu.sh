# A BuilderBot node on QEMU alone: no libvirt, no manager, one command.
# Run as a user who can reach /dev/kvm.
#
# Rendered by the dashboard's Create sandbox VM (vmtemplate.py). Two things
# this shape needs that a manager would do for you: the disk is made first,
# and UEFI keeps its variables in a file of its own, copied from the firmware
# the distribution ships.
set -eu

OVMF_CODE=/usr/share/OVMF/OVMF_CODE.fd     # RHEL: /usr/share/edk2/ovmf/OVMF_CODE.fd
OVMF_VARS=/usr/share/OVMF/OVMF_VARS.fd
VARS=${disk_dir}/${name}_VARS.fd

[ -f ${disk_path} ] || qemu-img create -f qcow2 ${disk_path} ${disk_gb}G
[ -f "$VARS" ] || cp "$OVMF_VARS" "$VARS"

qemu-system-x86_64 \
  -name ${name} -uuid ${uuid} \
  -enable-kvm -machine q35,accel=kvm -cpu host -smp ${cores} -m ${memory_mb} \
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
  -drive if=pflash,format=raw,file="$VARS" \
  -drive file=${disk_path},if=virtio,format=qcow2,discard=unmap \
  -cdrom ${iso_path} -boot order=dc \
  -netdev user,id=n0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=n0,mac=${mac} \
  -display none -serial mon:stdio
