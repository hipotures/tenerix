#!/bin/sh
# Write a verified 240 MiB image to the RN426 internal USB DOM, then verify by read-back.
# Run as root on the NAS (Alpine Live).
#   sh write-dom.sh                      image + .sha256 next to this script (nothing to type)
#   sh write-dom.sh IMAGE EXPECTED_SHA256   e.g. the factory backup to restore
set -eu
here=$(dirname "$0")
image=${1:-$here/tenerix-rn426-dom-system.img}
if [ $# -ge 2 ]; then
    expected=$2
else
    expected=$(cut -d' ' -f1 "$image.sha256")
fi
bytes=251658240

fail() { echo "STOP: $*" >&2; exit 1; }

[ -f "$image" ] || fail "$image is not a file"
[ "$(stat -c %s "$image")" = "$bytes" ] || fail "image is not exactly $bytes bytes"
echo "Checking image SHA-256 ..."
[ "$(sha256sum "$image" | cut -d' ' -f1)" = "$expected" ] || fail 'image SHA-256 does not match'

# The DOM: USB port 1-2, vendor:product 13fe:5200, exactly 491520 x 512-byte sectors.
usb=/sys/bus/usb/devices/1-2
[ "$(cat "$usb/idVendor"):$(cat "$usb/idProduct")" = 13fe:5200 ] || fail 'no 13fe:5200 device on USB 1-2'
set -- "$usb"/1-2:*/host*/target*/*/block/*
[ $# -eq 1 ] && [ -e "$1" ] || fail 'DOM block device not found or ambiguous'
name=${1##*/}
dev=/dev/$name
[ -b "$dev" ] || fail "$dev is not a block device"
[ "$(cat "/sys/class/block/$name/size")" = 491520 ] || fail "$dev is not 491520 sectors"

current=$(head -c "$bytes" "$dev" | sha256sum | cut -d' ' -f1)
echo "DOM device:      $dev (USB 1-2, 13fe:5200, 240 MiB)"
echo "DOM now:         $current"
case "$current" in
    40056ae60cf7bbae0b7945797066db7ae7665fb5da1f62e009ae4d0f1355dea7) echo '                 (= factory ReadyNAS DOM, backup exists)' ;;
    "$expected") echo 'DOM already contains this image; nothing to do.'; exit 0 ;;
esac
echo "Will write:      $image"
echo "Image SHA-256:   $expected"

# Unmount every mount of the DOM or its partitions (Alpine Live mounts it at /mnt/internal).
awk -v d="$dev" 'index($1, d) == 1 { print $2 }' /proc/mounts | sort -r | while read -r point; do
    echo "Unmounting $point"
    umount "$point"
done
if awk -v d="$dev" 'index($1, d) == 1' /proc/mounts | grep -q .; then fail 'DOM is still mounted'; fi

printf 'Type YES to overwrite the whole DOM %s: ' "$dev"
read -r answer
[ "$answer" = YES ] || fail 'not confirmed; nothing written'

dd if="$image" of="$dev" bs=1M conv=fsync
sync
blockdev --flushbufs "$dev" 2>/dev/null || true
echo 3 > /proc/sys/vm/drop_caches
echo 'Verifying by read-back ...'
after=$(head -c "$bytes" "$dev" | sha256sum | cut -d' ' -f1)
[ "$after" = "$expected" ] || fail "read-back SHA-256 $after does not match; restore the factory image"
echo "OK: DOM now contains $image ($after)"
