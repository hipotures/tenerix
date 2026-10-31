#!/bin/sh
# Run ONLY inside the local no-device toolbox; writes regular build-directory files.
set -eu
cd /work
out=/work/artifacts/dom/build
[ ! -e "$out/rootfs" ] || { echo 'Fresh rootfs output required' >&2; exit 1; }
mkdir -p "$out/rootfs"
root=$out/rootfs
apk verify /work/artifacts/alpine-hardware/packages/linux-lts-6.18.58-r0.apk
packages=$(sed '/^#/d; /^$/d' boot/rn426/packages.txt)
# No scripts: no kernel hooks, service actions or host initramfs alteration.
apk add --root "$root" --initdb --keys-dir /etc/apk/keys --no-scripts --no-cache \
 --repository https://dl-cdn.alpinelinux.org/alpine/v3.24/main \
 --repository https://dl-cdn.alpinelinux.org/alpine/v3.24/community \
 $packages /work/artifacts/alpine-hardware/packages/linux-lts-6.18.58-r0.apk
chroot "$root" /bin/busybox --install -s
mkdir -p "$root"/etc/tenerix "$root"/root/.ssh "$root"/opt/tenerix/front-panel/.upstream/rnpanel \
 "$root"/opt/tenerix/modules/6.18.58-0-lts "$root"/run "$root"/proc "$root"/sys "$root"/dev "$root"/tmp
chmod 1777 "$root/tmp"
chmod 700 "$root/root" "$root/root/.ssh"
cp artifacts/dom/test-admin.pub "$root/root/.ssh/authorized_keys"
chmod 600 "$root/root/.ssh/authorized_keys"
# Only the test guest gets an empty local-console root password. SSH passwords are disabled.
sed -i 's/^root:[^:]*:/root::/' "$root/etc/shadow"
cat > "$root/etc/ssh/sshd_config" <<'CFG'
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthorizedKeysFile .ssh/authorized_keys
Subsystem sftp internal-sftp
CFG
printf 'tenerix-zero\n' > "$root/etc/hostname"
cat > "$root/etc/inittab" <<'CFG'
::sysinit:/sbin/openrc sysinit
::sysinit:/sbin/openrc boot
::wait:/sbin/openrc default
ttyS0::respawn:/sbin/getty -L 115200 ttyS0 vt100
tty1::respawn:/sbin/getty 38400 tty1
::ctrlaltdel:/sbin/reboot
::shutdown:/sbin/openrc shutdown
CFG
cat > "$root/etc/fstab" <<'CFG'
/dev/md0 / ext4 defaults,noatime 0 0
CFG
# No blkid/MD hotplug hooks, no swap, no localmount/fstab discovery, no NFS export.
printf '# Device nodes from devtmpfs; no storage activation helpers.\n' > "$root/etc/mdev.conf"
printf 'AUTO -all\n' > "$root/etc/mdadm.conf"
printf 'coretemp\nixgbe\ne1000\n' > "$root/etc/modules"
cat > "$root/etc/network/interfaces" <<'CFG'
auto lo
iface lo inet loopback

auto eth3
iface eth3 inet dhcp
CFG
mac=$(cat artifacts/dom/build/network-mac)
printf '\tpre-up test "$(cat /sys/class/net/eth3/address)" = "%s"\n' "$mac" >> "$root/etc/network/interfaces"
rm -f "$root/etc/runlevels/"*/*
for entry in 'sysinit devfs' 'sysinit sysfs' 'sysinit dmesg' 'boot root' 'boot hostname' \
 'boot bootmisc' 'boot sysctl' 'boot modules' 'boot syslog' 'default networking' \
 'default sshd' 'shutdown killprocs' 'shutdown mount-ro'; do
 set -- $entry
 mkdir -p "$root/etc/runlevels/$1"
 ln -s "/etc/init.d/$2" "$root/etc/runlevels/$1/$2"
done
cp hardware/front-panel/panel.py hardware/front-panel/provenance.json hardware/front-panel/LICENSE "$root/opt/tenerix/front-panel/"
python3 - <<'PY'
import hashlib,json,shutil
from pathlib import Path
p=Path('hardware/front-panel'); pin=json.loads((p/'provenance.json').read_text())
for name,sha in pin['runtime_sha256'].items():
 source=p/'.upstream'/name
 assert hashlib.sha256(source.read_bytes()).hexdigest()==sha
 dest=Path('artifacts/dom/build/rootfs/opt/tenerix/front-panel/.upstream')/name
 dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
PY
cp artifacts/alpine-hardware/repro-one/it87.ko "$root/opt/tenerix/modules/6.18.58-0-lts/"
cp hardware/it8613e/alpine/compatibility.json "$root/etc/tenerix/it8613e-compatibility.json"
cp hardware/it8613e/COPYING "$root/opt/tenerix/modules/"
cp artifacts/dom/build/root.conf "$root/etc/tenerix/root.conf"
. artifacts/dom/build/root.conf
printf '%s\n' "$ROOT_FS_UUID" > "$root/etc/tenerix/root-fs-uuid"
# Kernel package scripts were skipped, so build module indexes against the local tree explicitly.
depmod -b "$root" 6.18.58-0-lts
apk --root "$root" info -v | sort > "$out/runtime-resolved.txt"
du -sk "$root" > "$out/rootfs-size.txt"
