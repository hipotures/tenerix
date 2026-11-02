#!/usr/bin/env python3
"""QEMU test of the disk system: six AHCI disks laid out like the RN426, DOM image with the new
boot entry. Checks: default "disk" entry assembles only the system mirror, ext4 root, OpenRC,
DHCP, sshd, password login, persistence across reboot, and the "dom" fallback entry."""
import json
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile

import pexpect

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from domlib import Fat  # noqa: E402

ROOT = Path('/work')
OUT = ROOT / 'artifacts/md-system'
TEST = OUT / 'test'
DOMSYS = ROOT / 'artifacts/dom-system'
KVER = '6.18.58-0-lts'
SECTORS = 9701440
PROMPT = r'tenerix-zero:[^\r\n]*# '
LAYOUT = ('label: gpt\nunit: sectors\nfirst-lba: 34\n'
          'start=64, size=8388608, type=A19D880F-05FC-4D3B-A006-743F0F84911E\n'
          'start=8388672, size=1048576, type=A19D880F-05FC-4D3B-A006-743F0F84911E\n'
          'start=9437248, size=262144, type=A19D880F-05FC-4D3B-A006-743F0F84911E\n')


def run(*args, **kw):
    print('+', *map(str, args), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kw)


def disks():
    return [TEST / f'disk-{i}.raw' for i in range(1, 7)]


def fixture():
    shutil.rmtree(TEST, ignore_errors=True)
    TEST.mkdir(parents=True)
    for disk in disks():
        with disk.open('xb') as f:
            f.truncate(SECTORS * 512)
        run('sfdisk', '--no-reread', '--no-tell-kernel', '-q', disk, input=LAYOUT, text=True)
    build = json.loads((OUT / 'build.json').read_text())
    (OUT / 'fixture.conf').write_text(
        f"SYSTEM_MD_UUID='{build['system_md_uuid']}'\nROOT_FS_UUID='{build['root_fs_uuid']}'\n"
        "SWAP_MD_UUID='a92b18e4:5875ee28:70d8d9bf:27b72dd4'\nDATA_MD_UUID='60d8af0f:acd5d295:c1345063:0e77954a'\n")
    full = ROOT / 'artifacts/dom/build/rootfs'
    features = TEST / 'features'
    features.mkdir()
    (features / 'fx.files').write_text('/bin/busybox\n/bin/sh\n/sbin/modprobe\n/sbin/mdadm\n/sbin/mke2fs\n')
    (features / 'fx.modules').write_text('kernel/drivers/md\nkernel/fs/ext4\nkernel/net/9p\nkernel/fs/9p\n'
                                         'kernel/drivers/block/virtio_blk.ko*\nkernel/drivers/virtio\nkernel/lib\n'
                                         'kernel/crypto\n')
    run('mkinitfs', '-b', str(full) + '/', '-P', features, '-F', 'fx', '-i', Path(__file__).with_name('fixture-init'),
        '-o', TEST / 'fixture-initramfs', KVER)
    cmd = ['qemu-system-x86_64', '-machine', 'pc,accel=tcg', '-cpu', 'max', '-smp', '2', '-m', '2048',
           '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-nic', 'none',
           '-kernel', str(DOMSYS / f'build/g1/vmlinuz-{KVER}'), '-initrd', str(TEST / 'fixture-initramfs'),
           '-append', 'console=ttyS0,115200n8 panic=0',
           '-virtfs', f'local,path={OUT},mount_tag=input,security_model=none,readonly=on']
    for i, disk in enumerate(disks()):
        cmd += ['-drive', f'if=none,format=raw,id=d{i},file={disk}',
                '-device', f'virtio-blk-pci,drive=d{i},serial=TENERIX-MDTEST-{"abcdef"[i]}']
    with (TEST / 'fixture.log').open('w') as log:
        guest = pexpect.spawn(cmd[0], cmd[1:], encoding='utf-8', codec_errors='replace', timeout=1200, echo=False)
        guest.logfile_read = log
        guest.expect(['FIXTURE_CREATED_CLEAN', 'FIXTURE_FAILED[^\r\n]*'])
        assert guest.after == 'FIXTURE_CREATED_CLEAN', guest.after
        guest.expect(pexpect.EOF, timeout=60)
    # DOM: the DOM system image plus the new boot files, as the NAS will have it.
    dom = TEST / 'dom.img'
    shutil.copyfile(DOMSYS / 'tenerix-rn426-dom-system.img', dom)
    fat = Fat(dom)
    with tarfile.open(OUT / 'tenerix-md-boot.tar') as t:
        t.extractall(TEST / 'boot', filter='data')
    fat.mkdir('md')
    for f in sorted((TEST / 'boot/md').iterdir()):
        fat.put(f, f'md/{f.name}')
    fat.delete('SYSLINUX.CFG')
    fat.put(TEST / 'boot/SYSLINUX.CFG', 'SYSLINUX.CFG')


def spawn(port, log, internet=False):
    cmd = ['qemu-system-x86_64', '-machine', 'pc,accel=tcg', '-cpu', 'max', '-smp', '2', '-m', '2048',
           '-display', 'none', '-serial', 'stdio', '-monitor', 'none',
           '-device', 'qemu-xhci,id=xhci', '-drive', f'if=none,format=raw,id=dom,file={TEST / "dom.img"}',
           '-device', 'usb-storage,drive=dom,bootindex=1', '-device', 'ahci,id=ahci']
    for i, disk in enumerate(disks()):
        cmd += ['-drive', f'if=none,format=raw,id=d{i},file={disk}', '-device', f'ide-hd,drive=d{i},bus=ahci.{i}']
    for i, mac in enumerate(['52:54:00:42:60:01', '52:54:00:42:60:02', '52:54:00:42:60:03', 'b0:b9:8a:45:13:fb']):
        forward = f',hostfwd=tcp:127.0.0.1:{port}-:22' if i == 3 else ''
        restrict = 'off' if internet and i == 3 else 'on'
        cmd += ['-netdev', f'user,id=n{i},restrict={restrict}{forward}', '-device', f'e1000,netdev=n{i},mac={mac}']
    if internet:
        cmd += ['-virtfs', f'local,path={OUT},mount_tag=input,security_model=none,readonly=on']
    guest = pexpect.spawn(cmd[0], cmd[1:], encoding='utf-8', codec_errors='replace', timeout=300, echo=False)
    guest.logfile_read = log
    return guest


def marker(guest, commands, name):
    head, tail = name.rsplit('_', 1)
    guest.send(f"{commands}; printf '%s_{tail}\\n' {head}\r")
    guest.expect(rf'\n{name}\r*\n')
    return guest.before.replace('\r', '') + '\n'


def login(guest, password):
    guest.expect('tenerix-zero login:')
    guest.send('root\r')
    guest.expect('Password:')
    guest.send(password + '\r')
    guest.expect(PROMPT)


def boot():
    password = (DOMSYS / 'root-password').read_text().strip()
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    result = {'passed': False}
    with (TEST / 'boot.log').open('w') as log:
        guest = spawn(port, log)
        try:
            guest.expect('SYSLINUX 6.03')
            guest.expect('TENERIX_SWITCH_ROOT disk build=disk-1 device=/dev/md0 fs=ext4 members=6')
            login(guest, password)
            out = marker(guest, 'uname -r; cat /proc/mdstat; cat /proc/mounts; cat /proc/swaps; rc-status; '
                         'ip -4 -o addr; modinfo -n it87; ls /lib/modules/6.18.58-0-lts/kernel/fs/btrfs', 'PROBE_DONE')
            assert re.search(r'/dev/md0 / ext4 rw', out), 'root is not md0 ext4'
            assert re.search(r'md0 : active raid1 .*\n\s+\d+ blocks super 1\.2 \[6/6\]', out), 'md0 not 6/6'
            assert not re.search(r'^md(?!0 )\d+ :', out, re.M), 'another array was assembled'
            assert '/dev/md' not in out.split('Priority', 1)[1].split('Runlevel', 1)[0], 'swap active'
            assert re.search(r'eth3\s+inet 10\.0\.2\.15/', out) and re.search(r'sshd\s+\[\s*started', out)
            assert 'updates/it87.ko' in out and 'btrfs.ko' in out
            result.update({'disk_root': True, 'only_system_mirror': True, 'dhcp_ssh': True, 'full_modules': True})
            banner = subprocess.run(['ssh-keyscan', '-p', str(port), '127.0.0.1'], capture_output=True,
                                    text=True, timeout=60).stdout
            assert 'ssh-ed25519' in banner
            guest.expect(PROMPT)
            nonce = 'TENERIX_' + secrets.token_hex(8)
            guest.send(f'echo {nonce} > /root/persistence; sync; reboot\r')
            guest.expect('SYSLINUX 6.03', timeout=180)
            guest.expect('TENERIX_SWITCH_ROOT disk')
            login(guest, password)
            assert f'\n{nonce}\n' in marker(guest, 'cat /root/persistence', 'REBOOT_DONE')
            result['reboot_persistence'] = True
            guest.expect(PROMPT)
            guest.send('poweroff\r')
            guest.expect(pexpect.EOF, timeout=180)
            guest.close()
            log.write('\n=== TENERIX TEST: cold boot, select dom ===\n')
            guest = spawn(port, log)
            guest.expect('boot:')
            guest.send('dom\r')
            guest.expect('TENERIX_SWITCH_ROOT generation=g1 build=dom-1 device=/dev/loop0')
            login(guest, password)
            result['dom_fallback'] = True
            guest.send('poweroff\r')
            guest.expect(pexpect.EOF, timeout=180)
            result['passed'] = True
        except BaseException as error:
            result['error'] = str(error)[:1500]
            raise
        finally:
            if guest.isalive():
                guest.close(force=True)
            (TEST / 'boot.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2), flush=True)


def upgrade():
    """The NAS procedure: install the kernel-update package, apk add the current kernel, reboot."""
    password = (DOMSYS / 'root-password').read_text().strip()
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    result = {'passed': False}
    with (TEST / 'upgrade.log').open('w') as log:
        guest = spawn(port, log, internet=True)
        try:
            guest.expect('TENERIX_SWITCH_ROOT disk')
            login(guest, password)
            out = marker(guest, 'modprobe -a virtio_pci 9pnet_virtio 9p; mkdir -p /mnt/in && mount -t 9p -o trans=virtio,version=9p2000.L,ro input /mnt/in '
                         '&& tar -xf /mnt/in/tenerix-kernel-update.tar -C / && umount /mnt/in && uname -r', 'COPY_DONE')
            assert '6.18.58-0-lts' in out
            guest.send("apk add -u linux-lts linux-lts-dev build-base mkinitfs 2>&1 | tail -25; "
                       "printf '%s_DONE\\n' APK\r")
            guest.expect(r'\nAPK_DONE\r*\n', timeout=2400)
            out = guest.before.replace('\r', '')
            assert 'DOM now boots 6.18.59-0-lts by default' in out, 'update hook did not finish'
            result['hook_output'] = [l for l in out.splitlines() if 'tenerix-kernel' in l]
            guest.expect(PROMPT)
            # The update leaves the DOM unmounted; a later run with the same kernel does not mount it.
            out = marker(guest, 'echo "mounted=$(grep -c " /media/dom " /proc/mounts)"; '
                         'tenerix-kernel-update; echo "mounted=$(grep -c " /media/dom " /proc/mounts)"; '
                         'cat /var/lib/tenerix/dom-kernel', 'STATE_DONE')
            assert out.count('mounted=0') == 2, 'DOM left mounted'
            assert 'DOM already boots 6.18.59-0-lts (recorded); DOM not mounted' in out
            guest.expect(PROMPT)
            out = marker(guest, 'dom=$(grep -l "^PARTUUID=fd8988d9-01$" /sys/class/block/*/uevent); '
                         'dom=/dev/$(basename "$(dirname "$dom")"); mount -t vfat -o ro "$dom" /media/dom; '
                         'cat /media/dom/SYSLINUX.CFG; umount /media/dom; ls /lib/modules; modinfo -n it87; '
                         'modinfo -F vermagic /lib/modules/6.18.59-0-lts/updates/it87.ko; lsmod | grep -c e1000', 'CHECK_DONE')
            assert 'LINUX /k/6.18.59-0-lts/vmlinuz' in out and 'LABEL disk-previous' in out
            assert 'LINUX /g1/vmlinuz-6.18.58-0-lts' in out and 'LABEL dom' in out and 'LABEL recovery' in out
            assert '6.18.58-0-lts/updates/it87.ko' in out, 'running kernel lost its it87'
            assert re.search(r'^6\.18\.59-0-lts SMP', out, re.M), 'it87 not built for 6.18.59'
            result['dom_updated'] = True
            guest.expect(PROMPT)
            guest.send('reboot\r')
            guest.expect('TENERIX_SWITCH_ROOT disk', timeout=300)
            login(guest, password)
            out = marker(guest, 'uname -r; modinfo -n it87; ip -4 -o addr; rc-status | grep -E "sshd|networking"', 'NEW_DONE')
            assert '\n6.18.59-0-lts\n' in out and '6.18.59-0-lts/updates/it87.ko' in out
            assert re.search(r'eth3\s+inet 10\.0\.2\.15/', out) and re.search(r'sshd\s+\[\s*started', out)
            result['new_kernel_boot'] = True
            guest.expect(PROMPT)
            guest.send('poweroff\r')
            guest.expect(pexpect.EOF, timeout=180)
            guest.close()
            log.write('\n=== TENERIX TEST: cold boot, select disk-previous ===\n')
            guest = spawn(port, log)
            guest.expect('boot:')
            guest.send('disk-previous\r')
            guest.expect('TENERIX_SWITCH_ROOT disk')
            login(guest, password)
            out = marker(guest, 'uname -r; ip -4 -o addr; modinfo -n it87', 'OLD_DONE')
            assert '\n6.18.58-0-lts\n' in out and re.search(r'eth3\s+inet 10\.0\.2\.15/', out)
            assert '6.18.58-0-lts/updates/it87.ko' in out
            result['previous_kernel_boot'] = True
            guest.send('poweroff\r')
            guest.expect(pexpect.EOF, timeout=180)
            result['passed'] = True
        except BaseException as error:
            result['error'] = str(error)[:1500]
            raise
        finally:
            if guest.isalive():
                guest.close(force=True)
            (TEST / 'upgrade.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    {'fixture': fixture, 'upgrade': upgrade}.get(sys.argv[1] if len(sys.argv) > 1 else '', boot)()
