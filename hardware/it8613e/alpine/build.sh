#!/bin/sh
# External module build only; never installs, loads or touches a target machine.
set -eu
cd "$(dirname "$0")/.."
kver=6.18.58-0-lts
kdir=/usr/src/linux-headers-$kver
out=${1:?Usage: alpine/build.sh ABSOLUTE_OUTPUT_DIRECTORY}
case "$out" in /*) ;; *) echo 'Output path must be absolute' >&2; exit 1;; esac
[ "$(cat "$kdir/include/config/kernel.release")" = "$kver" ]
echo '24cbcda9272285a9e10a09d19a971715a15c17c242757e8729f0f28bac7eac71  /usr/src/linux-headers-6.18.58-0-lts/.config' | sha256sum -c -
echo '673788496cd0724536a305bae2b1d1b7901fedf052ccd8e2d10efc9404b6037a  /usr/src/linux-headers-6.18.58-0-lts/Module.symvers' | sha256sum -c -
sha256sum -c SOURCES.sha256
mkdir -p "$out"
[ ! -e "$out/it87.c" ] || { echo 'Use a fresh output directory' >&2; exit 1; }
cp upstream/linux-6.12.107-it87.c "$out/it87.c"
patch --batch --fuzz=0 --no-backup-if-mismatch -d "$out" -p1 < patches/0001-backport-it8613e-linux-6.12.107.patch
cp Kbuild "$out/Kbuild"
export KBUILD_BUILD_USER=rn426-audit KBUILD_BUILD_HOST=reproducible
export KBUILD_BUILD_TIMESTAMP='2026-10-31 00:00:00 UTC' KBUILD_BUILD_VERSION=1
export SOURCE_DATE_EPOCH=1793404800
make -C "$kdir" M="$out" -j2 W=1 KCFLAGS="-ffile-prefix-map=$out=/usr/src/rn426-it8613e -frandom-seed=rn426-it8613e-6.18.58" modules
