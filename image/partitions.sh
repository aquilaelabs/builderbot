# The appliance disk's partitions (R160 step 1), one place for every number
# the image's parts share: build.sh lays the disk out by them, the initramfs
# script mounts by them, fstab names the ESP by one, grub.cfg boots a slot by
# one, and test_image.py holds the three copies to this file. A partition's
# UUID is fixed, the same on every stick and every installed disk, so a slot
# is found by what it is rather than by where a firmware put it; two
# BuilderBot disks in one machine are not a case the appliance serves.
#
# shellcheck disable=SC2034  # read by the scripts that source it
BB_PART_BIOS=6a5c2f3e-0b7d-4b2a-9c1e-b0b1de5b0e00   # GRUB's BIOS core, 1 MiB
BB_PART_ESP=6a5c2f3e-0b7d-4b2a-9c1e-b0b1de5b0e01    # the ESP: GRUB, its env, each slot's kernel
BB_PART_ROOT_A=6a5c2f3e-0b7d-4b2a-9c1e-b0b1de5b0e0a # root slot A, a squashfs
BB_PART_ROOT_B=6a5c2f3e-0b7d-4b2a-9c1e-b0b1de5b0e0b # root slot B, empty until an update
BB_PART_DATA=6a5c2f3e-0b7d-4b2a-9c1e-b0b1de5b0e0d   # /var, and under it /etc's changes
BB_ESP_FSUUID=BB00-B007                             # the ESP's FAT serial, what GRUB searches for
BB_ESP_LABEL=BBBOOT
BB_DATA_LABEL=bbdata
BB_SIZE_ESP_MIB=512
BB_SIZE_SLOT_MIB=4096
BB_SIZE_DATA_MIB=2048
