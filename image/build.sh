#!/usr/bin/env bash
# Builds the appliance image (R160 step 1): the Debian tree by mkosi, pinned
# to image/SNAPSHOT, sealed as a read-only squashfs and laid into a disk with
# two root slots, GRUB for UEFI and BIOS, and a data partition. Root, since
# mkosi installs packages and the disk is assembled on a loop device.
#
#   sudo image/build.sh [--out DIR] [--tree-only] [--from-tree DIR]
#
# What comes out, under DIR (image/out by default), each with its .sha256:
#   builderbot-os-VERSION.raw.zst        the whole disk (the VM disk, the USB stick and the installer start here)
#   builderbot-os-VERSION.root.squashfs  one root slot, what an update writes into the other slot (R160 step 4)
#   builderbot-os-VERSION.vmlinuz        the slot's kernel and initrd, kept on the ESP beside it
#   builderbot-os-VERSION.initrd
#   builderbot-os-VERSION.release        the stamp the image carries at /usr/lib/builderbot-os/release
#
# --tree-only stops after mkosi (the tree under DIR/mkosi/tree, for a look);
# --from-tree DIR assembles the disk from a tree built before. The partition
# numbers are image/partitions.sh's, and docs/image.md says why each is so.
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
    need mkosi "pip install mkosi==${MKOSI_PIN} (what the image workflow pins)"
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
cat > "$TREE/usr/lib/builderbot-os/release" <<REL
BUILDERBOT_OS_VERSION=${VERSION}
BUILDERBOT_VERSION=$(head -1 "$TREE_SRC/VERSION" | tr -d '[:space:]')
DEBIAN_SNAPSHOT=${SNAPSHOT}
BUILT=$(date -u -d "@$SOURCE_DATE_EPOCH" +%Y-%m-%dT%H:%M:%SZ)
REL
cp "$TREE/usr/lib/builderbot-os/release" "$OUT/$NAME.release"
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
for t in sfdisk losetup mkfs.vfat mkfs.ext4 grub-install zstd partprobe; do need "$t" "the image workflow installs it (grub-efi-amd64-bin, grub-pc-bin, dosfstools, e2fsprogs, fdisk, zstd)"; done
[ -d /usr/lib/grub/x86_64-efi ] || die "grub-efi-amd64-bin is not here: GRUB for UEFI"
[ -d /usr/lib/grub/i386-pc ] || die "grub-pc-bin is not here: GRUB for BIOS"
say "the disk: ${NAME}.raw"
RAW="$OUT/$NAME.raw"
rm -f "$RAW" "$RAW.zst"
TOTAL_MIB=$(( 1 + 1 + BB_SIZE_ESP_MIB + 2 * BB_SIZE_SLOT_MIB + BB_SIZE_DATA_MIB + 2 ))
truncate -s "${TOTAL_MIB}M" "$RAW"
sfdisk --quiet --wipe always "$RAW" <<PT
label: gpt
unit: sectors
sector-size: 512
start=2048, size=2048, type=21686148-6449-6E6F-744E-656564454649, uuid=${BB_PART_BIOS}, name=bios
size=${BB_SIZE_ESP_MIB}MiB, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, uuid=${BB_PART_ESP}, name=esp
size=${BB_SIZE_SLOT_MIB}MiB, type=4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709, uuid=${BB_PART_ROOT_A}, name=bbroot-a
size=${BB_SIZE_SLOT_MIB}MiB, type=4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709, uuid=${BB_PART_ROOT_B}, name=bbroot-b
type=4D21B016-B534-45C2-A9FB-5C16E091FD2D, uuid=${BB_PART_DATA}, name=bbdata
PT
LOOP="$(losetup --find --show --partscan "$RAW")"
MNT="$(mktemp -d)"
cleanup() { umount "$MNT" 2>/dev/null || true; rmdir "$MNT" 2>/dev/null || true; losetup -d "$LOOP" 2>/dev/null || true; }
trap cleanup EXIT
partprobe "$LOOP" 2>/dev/null || true
udevadm settle 2>/dev/null || sleep 1
P() { printf '%sp%s' "$LOOP" "$1"; }
# The ESP: GRUB for both firmwares with one menu, its environment naming
# slot A, and slot A's kernel and initrd.
mkfs.vfat -F 32 -i "${BB_ESP_FSUUID/-/}" -n "$BB_ESP_LABEL" "$(P 2)" >/dev/null
mount "$(P 2)" "$MNT"
grub-install --target=x86_64-efi --efi-directory="$MNT" --boot-directory="$MNT" --removable --no-nvram "$LOOP" >/dev/null 2>&1 \
    || die "grub-install for UEFI failed"
grub-install --target=i386-pc --boot-directory="$MNT" "$LOOP" >/dev/null 2>&1 \
    || die "grub-install for BIOS failed"
install -m 0644 "$HERE/grub.cfg" "$MNT/grub/grub.cfg"
grub-editenv "$MNT/grub/grubenv" create
grub-editenv "$MNT/grub/grubenv" set bb_slot=a
install -d "$MNT/builderbot/a" "$MNT/builderbot/b"
install -m 0644 "$OUT/$NAME.vmlinuz" "$MNT/builderbot/a/vmlinuz"
install -m 0644 "$OUT/$NAME.initrd" "$MNT/builderbot/a/initrd"
install -m 0644 "$OUT/$NAME.release" "$MNT/builderbot/a/release"
umount "$MNT"
# Slot A: the squashfs as it is. Slot B: nothing, until an update.
dd if="$OUT/$NAME.root.squashfs" of="$(P 3)" bs=4M conv=fsync status=none
# The data partition: /var as the tree has it, so the first boot finds
# Debian's own skeleton under it; the state and the projects grow there.
mkfs.ext4 -q -L "$BB_DATA_LABEL" -d "$TREE/var" -E lazy_itable_init=0,lazy_journal_init=0 "$(P 5)"
cleanup; trap - EXIT
say "compressing"
zstd -q -T0 -19 --rm "$RAW" -o "$RAW.zst"

# ---- the stamps -------------------------------------------------------------
( cd "$OUT" && for f in "$NAME.raw.zst" "$NAME.root.squashfs" "$NAME.vmlinuz" "$NAME.initrd" "$NAME.release"; do sha256sum "$f" > "$f.sha256"; done )
say "done"
for f in "$OUT/$NAME".*; do printf '   %s  %s\n' "$(stat -c %s "$f")" "$(basename "$f")"; done
