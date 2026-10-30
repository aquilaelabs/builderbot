#!/usr/bin/env bash
# Builds the appliance image (R160 step 1): the Debian tree by mkosi, pinned
# to image/SNAPSHOT, sealed as a read-only squashfs and laid into a disk with
# two root slots, GRUB for UEFI and BIOS, and a data partition. Root, since
# mkosi installs packages and the disk is assembled on a loop device.
#
#   sudo image/build.sh [--out DIR] [--tree-only] [--from-tree DIR]
#
# What comes out, under DIR (image/out by default), each with its .sha256:
#   builderbot-os-VERSION.raw.xz         the whole disk, for an installed machine or a VM
#   builderbot-os-VERSION.stick.raw.xz   the same disk with GRUB loading the slot into memory: the USB edition
#   builderbot-os-VERSION.iso            the installer: boots the same root live, lays a disk out with lay-disk
#   builderbot-os-VERSION.qcow2          the same disk for Proxmox, libvirt and other QEMU hosts
#   builderbot-os-VERSION.ova            the same disk for VMware and VirtualBox (a stream-optimized VMDK with its descriptor)
#   builderbot-os-VERSION.root.squashfs  one root slot, what an update writes into the other slot (R160 step 4)
#   builderbot-os-VERSION.vmlinuz        the slot's kernel and initrd, kept on the ESP beside it
#   builderbot-os-VERSION.initrd
#   builderbot-os-VERSION.release        the stamp the image carries at /usr/lib/builderbot-os/release
#   builderbot-os-VERSION.packages       every package in it with its version, for the weekly rebuild's diff
#
# --tree-only stops after mkosi (the tree under DIR/mkosi/tree, for a look);
# --from-tree DIR assembles the disk from a tree built before. The disk is
# image/lay-disk's, its numbers image/partitions.sh's, and docs/image.md
# says why each is so.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TREE_SRC="$(cd "$HERE/.." && pwd)"
# shellcheck source=image/partitions.sh
. "$HERE/partitions.sh"
OUT="$HERE/out"
TREE_ONLY=0
FROM_TREE=""
MKOSI_PIN="${MKOSI_PIN:-25.3}"

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }
die() { echo "build.sh: $*" >&2; exit 1; }
say() { printf '\n== %s\n' "$*"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --out) OUT="$(realpath -m "${2:?--out needs a directory}")"; shift 2 ;;
        --tree-only) TREE_ONLY=1; shift ;;
        --from-tree) FROM_TREE="$(realpath "${2:?--from-tree needs a directory}")"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 1 ;;
    esac
done

# ---- what this build is -----------------------------------------------------
SNAPSHOT="$(tr -d '[:space:]' < "$HERE/SNAPSHOT")"
case "$SNAPSHOT" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) ;; *) die "image/SNAPSHOT is not a snapshot.debian.org timestamp (YYYYMMDDTHHMMSSZ): $SNAPSHOT" ;; esac
MIRROR="https://snapshot.debian.org/archive/debian/${SNAPSHOT}/"
version() {
    local target tag ordinal short
    target="$(head -1 "$TREE_SRC/VERSION" 2>/dev/null | tr -d '[:space:]')"
    if tag="$(git -C "$TREE_SRC" describe --tags --exact-match HEAD 2>/dev/null)"; then printf '%s' "${tag#v}"; return; fi
    if [ -d "$TREE_SRC/.git" ] || [ -f "$TREE_SRC/.git" ]; then
        ordinal="$(git -C "$TREE_SRC" rev-list --count HEAD 2>/dev/null || echo 0)"
        short="$(git -C "$TREE_SRC" rev-parse --short=7 HEAD 2>/dev/null || echo unstamped)"
        printf '%s-dev.%s+%s' "${target:-0.0.0}" "$ordinal" "$short"; return
    fi
    printf '%s' "${target:-unstamped}"
}
VERSION="$(version)"
NAME="builderbot-os-${VERSION}"
# One day, not now: every file in the tree and the squashfs is stamped with
# the snapshot's day, so the same inputs make the same image.
SOURCE_DATE_EPOCH="$(date -u -d "${SNAPSHOT:0:8} ${SNAPSHOT:9:2}:${SNAPSHOT:11:2}:${SNAPSHOT:13:2}" +%s)"
export SOURCE_DATE_EPOCH

need() { command -v "$1" >/dev/null 2>&1 || die "$1 is not here: $2"; }
[ "$(id -u)" -eq 0 ] || die "run as root: mkosi installs packages and the disk is assembled on a loop device"
mkdir -p "$OUT"

# ---- the tree, by mkosi -----------------------------------------------------
TREE="$FROM_TREE"
if [ -z "$TREE" ]; then
    need mkosi "pip install 'mkosi @ https://github.com/systemd/mkosi/archive/refs/tags/v${MKOSI_PIN}.tar.gz' (what the image workflow pins; mkosi is not on PyPI)"
    say "mkosi ${MKOSI_PIN}: Debian trixie from ${MIRROR}"
    # The controller's own packages, from the one list the Dockerfile and a
    # bare-metal install read, as a second packages file beside mkosi.conf.
    {
        echo "[Content]"
        echo "Packages="
        bash "$TREE_SRC/scripts/lib/controller-packages.sh" deb core tools host | sed 's/^/        /'
    } > "$OUT/controller-packages.conf"
    rm -rf "$OUT/mkosi"
    mkdir -p "$OUT/mkosi"
    mkosi --directory "$HERE" --output-directory "$OUT/mkosi" --mirror "$MIRROR" \
          --include "$OUT/controller-packages.conf" \
          --environment "BUILDERBOT_OS_VERSION=$VERSION" --environment "BUILDERBOT_OS_REV=$(git -C "$TREE_SRC" rev-parse HEAD 2>/dev/null || echo unstamped)" \
          --force build
    TREE="$OUT/mkosi/tree"
fi
[ -d "$TREE/usr/lib/builderbot-os" ] || die "no BuilderBot OS tree at $TREE"
# What the installer on the ISO lays a disk out with (R160 step 2): the
# same layout script, numbers and menu this build uses, in the image.
install -m 0755 "$HERE/lay-disk" "$TREE/usr/lib/builderbot-os/lay-disk"
install -m 0644 "$HERE/partitions.sh" "$TREE/usr/lib/builderbot-os/partitions.sh"
install -m 0644 "$HERE/grub.cfg" "$TREE/usr/lib/builderbot-os/grub.cfg"
cat > "$TREE/usr/lib/builderbot-os/release" <<REL
BUILDERBOT_OS_VERSION=${VERSION}
BUILDERBOT_VERSION=$(head -1 "$TREE_SRC/VERSION" | tr -d '[:space:]')
DEBIAN_SNAPSHOT=${SNAPSHOT}
BUILT=$(date -u -d "@$SOURCE_DATE_EPOCH" +%Y-%m-%dT%H:%M:%SZ)
REL
cp "$TREE/usr/lib/builderbot-os/release" "$OUT/$NAME.release"
# Every package in the image with its version (R160 step 6): what the weekly
# rebuild compares against the last release's to say what moved.
# From mkosi's manifest, recorded before CleanPackageMetadata removes the
# package database the tree would otherwise carry; a tree that still has
# that database (one built with --from-tree, or by hand) is read directly.
MANIFEST="$OUT/mkosi/tree.manifest"
if [ -f "$MANIFEST" ]; then
    python3 -c 'import json, sys; [print(p["name"], p["version"]) for p in json.load(open(sys.argv[1]))["packages"]]' "$MANIFEST" | sort > "$OUT/$NAME.packages"
elif [ -f "$TREE/var/lib/dpkg/status" ]; then
    awk '/^Package: /{p=$2} /^Version: /{v=$2} /^$/{if(p!=""&&v!="")print p" "v; p="";v=""}' "$TREE/var/lib/dpkg/status" | sort > "$OUT/$NAME.packages"
else
    die "no package list: neither $MANIFEST nor the tree's dpkg status is there"
fi
if [ "$TREE_ONLY" = 1 ]; then say "tree at $TREE"; exit 0; fi

# ---- the slot: a squashfs, its kernel and initrd ----------------------------
need mksquashfs "squashfs-tools"
say "the root slot"
KERNEL="$(find "$TREE/boot" -maxdepth 1 -name 'vmlinuz-*' | sort -V | tail -1)"
INITRD="$(find "$TREE/boot" -maxdepth 1 -name 'initrd.img-*' | sort -V | tail -1)"
[ -f "$KERNEL" ] && [ -f "$INITRD" ] || die "the tree has no kernel and initrd under /boot"
cp "$KERNEL" "$OUT/$NAME.vmlinuz"; cp "$INITRD" "$OUT/$NAME.initrd"
rm -f "$OUT/$NAME.root.squashfs"
mksquashfs "$TREE" "$OUT/$NAME.root.squashfs" -comp zstd -Xcompression-level 19 -xattrs -noappend -quiet \
    -e proc sys dev run tmp var/cache/apt var/lib/apt/lists -mkfs-time "$SOURCE_DATE_EPOCH" -all-time "$SOURCE_DATE_EPOCH"
SQ_MIB=$(( ($(stat -c %s "$OUT/$NAME.root.squashfs") + 1048575) / 1048576 ))
[ "$SQ_MIB" -lt "$BB_SIZE_SLOT_MIB" ] || die "the root squashfs is ${SQ_MIB} MiB and a slot holds ${BB_SIZE_SLOT_MIB}: fewer packages, or a bigger slot in image/partitions.sh"

# ---- the disk ---------------------------------------------------------------
# Laid out by image/lay-disk on a loop device, the same script the installer
# on the ISO runs on a person's disk (R160 step 2), so the two cannot differ.
for t in sfdisk losetup mkfs.vfat mkfs.ext4 grub-install xz partprobe; do need "$t" "the image workflow installs it (grub-efi-amd64-bin, grub-pc-bin, dosfstools, e2fsprogs, fdisk, xz-utils)"; done
say "the disk: ${NAME}.raw"
RAW="$OUT/$NAME.raw"
rm -f "$RAW" "$RAW.xz" "$OUT/$NAME.stick.raw" "$OUT/$NAME.stick.raw.xz"
TOTAL_MIB=$(( 1 + 1 + BB_SIZE_ESP_MIB + 2 * BB_SIZE_SLOT_MIB + BB_SIZE_DATA_MIB + 2 ))
truncate -s "${TOTAL_MIB}M" "$RAW"
LOOP="$(losetup --find --show --partscan "$RAW")"
trap 'losetup -d "$LOOP" 2>/dev/null || true' EXIT
bash "$HERE/lay-disk" "$LOOP" "$OUT/$NAME.root.squashfs" "$OUT/$NAME.vmlinuz" "$OUT/$NAME.initrd" "$OUT/$NAME.release" "$HERE/grub.cfg" --var "$TREE/var"
losetup -d "$LOOP"; trap - EXIT

# ---- the ISO (R160 step 2) --------------------------------------------------
# The same root, kernel and initrd on a medium a machine boots from (live-boot
# finds live/filesystem.squashfs), its menu offering the installer, which lays
# a disk out with the copy of lay-disk the image carries. grub-mkrescue
# makes it boot under UEFI and BIOS alike.
need grub-mkrescue "grub-common"
need xorriso "xorriso (and mtools, for the EFI image)"
say "the ISO: ${NAME}.iso"
ISO="$(mktemp -d)"
install -d "$ISO/live" "$ISO/boot/grub"
ln -s "$OUT/$NAME.root.squashfs" "$ISO/live/filesystem.squashfs"
install -m 0644 "$OUT/$NAME.vmlinuz" "$ISO/live/vmlinuz"
install -m 0644 "$OUT/$NAME.initrd" "$ISO/live/initrd"
install -m 0644 "$OUT/$NAME.release" "$ISO/live/release"
install -m 0644 "$HERE/iso-grub.cfg" "$ISO/boot/grub/grub.cfg"
grub-mkrescue -o "$OUT/$NAME.iso" "$ISO" -- -follow_links -volid BUILDERBOT_OS >/dev/null 2>&1 \
    || die "grub-mkrescue did not make the ISO"
rm -rf "$ISO"

# ---- the same disk for a hypervisor (R160 step 3) ---------------------------
# qcow2 for Proxmox, libvirt and other QEMU hosts; an OVA (a stream-optimized VMDK with
# its descriptor and manifest) for VMware and VirtualBox. Converted from the
# raw disk, never laid out again, so the three cannot drift.
say "the VM disks"
need qemu-img "qemu-utils"
qemu-img convert -O qcow2 -c "$RAW" "$OUT/$NAME.qcow2"
OVA="$(mktemp -d)"
qemu-img convert -O vmdk -o subformat=streamOptimized "$RAW" "$OVA/$NAME-disk1.vmdk"
sed -e "s|@NAME@|$NAME|g" -e "s|@VMDK@|$NAME-disk1.vmdk|g" \
    -e "s|@VMDK_SIZE@|$(stat -c %s "$OVA/$NAME-disk1.vmdk")|g" -e "s|@CAPACITY@|$(stat -c %s "$RAW")|g" \
    "$HERE/ovf.xml" > "$OVA/$NAME.ovf"
( cd "$OVA" && { printf 'SHA256(%s)= %s\n' "$NAME.ovf" "$(sha256sum "$NAME.ovf" | cut -d' ' -f1)";
                 printf 'SHA256(%s)= %s\n' "$NAME-disk1.vmdk" "$(sha256sum "$NAME-disk1.vmdk" | cut -d' ' -f1)"; } > "$NAME.mf" \
  && tar -cf "$OUT/$NAME.ova" --owner=0 --group=0 --mtime="@$SOURCE_DATE_EPOCH" "$NAME.ovf" "$NAME.mf" "$NAME-disk1.vmdk" )
rm -rf "$OVA"
# The USB edition (R161 steps 1 and 5): the same disk with bb_toram=1 in
# GRUB's environment, so a stick written from it runs from memory; the
# stick maker (tools/builderbot-stick.py) writes this one.
say "the stick: ${NAME}.stick.raw"
STICK="$OUT/$NAME.stick.raw"
cp --reflink=auto --sparse=always "$RAW" "$STICK"
LOOP="$(losetup --find --show --partscan "$STICK")"
trap 'losetup -d "$LOOP" 2>/dev/null || true' EXIT
MNT="$(mktemp -d)"
mount "${LOOP}p2" "$MNT"
grub-editenv "$MNT/grub/grubenv" set bb_toram=1
umount "$MNT"; rmdir "$MNT"
losetup -d "$LOOP"; trap - EXIT
say "compressing"
# xz rather than zstd: a stick maker with nothing but Python's own library
# opens it on Windows, a Mac and Linux alike (lzma is in the standard library).
xz -q -T0 -6 "$RAW"
xz -q -T0 -6 "$STICK"

# ---- the stamps -------------------------------------------------------------
( cd "$OUT" && for f in "$NAME.raw.xz" "$NAME.stick.raw.xz" "$NAME.iso" "$NAME.qcow2" "$NAME.ova" "$NAME.root.squashfs" "$NAME.vmlinuz" "$NAME.initrd" "$NAME.release" "$NAME.packages"; do sha256sum "$f" > "$f.sha256"; done )
say "done"
for f in "$OUT/$NAME".*; do printf '   %s  %s\n' "$(stat -c %s "$f")" "$(basename "$f")"; done
