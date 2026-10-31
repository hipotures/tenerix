#!/usr/bin/env python3
"""Build the disk system for the RN426 system mirror. Run inside the tenerix-dom-tools container.

Base: the DOM system rootfs (network, keys, fan keeper, login summary), with the full module
tree of the same kernel. Outputs in artifacts/md-system/:
  tenerix-md-root.tar.gz   root filesystem to extract onto the freshly made ext4 on the mirror
  tenerix-md-boot.tar      md/initramfs + SYSLINUX.CFG for the DOM FAT (new default entry "disk")
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from domlib import run, sha256  # noqa: E402

ROOT = Path('/work')
OUT = ROOT / 'artifacts/md-system'
BUILD = OUT / 'build'
BASE = ROOT / 'artifacts/dom-system/build/rootfs'
FULL_MODULES = ROOT / 'artifacts/dom/build/rootfs/lib/modules'
KVER = '6.18.58-0-lts'
SYSTEM_MD_UUID = '58b7f1b0:9d294f2c:2bd63fbf:960d5376'
ROOT_FS_UUID = '25e85b7f-ffee-4088-86fc-a2f946fafb6a'
BUILD_ID = 'disk-1'
APPEND = 'console=tty0 console=ttyS0,115200n8 panic=0 raid=noautodetect'
SYSLINUX = f'''SERIAL 0 115200 0
CONSOLE 1
PROMPT 1
TIMEOUT 30
TOTALTIMEOUT 30
DEFAULT disk
ONTIMEOUT disk
ONERROR dom
SAY Tenerix Zero RN426: disk (system mirror) / dom / dom-previous / recovery (RAM shell)
LABEL disk
  LINUX /g1/vmlinuz-{KVER}
  INITRD /g1/ucode-c3538.cpio,/md/initramfs-{KVER}
  APPEND {APPEND}
LABEL dom
  LINUX /g1/vmlinuz-{KVER}
  INITRD /g1/ucode-c3538.cpio,/g1/initramfs-{KVER}
  APPEND {APPEND} tenerix.slot=g1
LABEL dom-previous
  LINUX /g0/vmlinuz-{KVER}
  INITRD /g0/ucode-c3538.cpio,/g0/initramfs-{KVER}
  APPEND {APPEND} tenerix.slot=g0
LABEL recovery
  LINUX /g1/vmlinuz-{KVER}
  INITRD /rescue/recovery-{KVER}
  APPEND {APPEND}
'''


def write(root, path, text, mode=0o644):
    target = root / path.lstrip('/')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    target.chmod(mode)


def main():
    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir(parents=True)
    root = BUILD / 'rootfs'
    run('cp', '-a', BASE, root)
    # Full module tree of the same kernel (4 GiB root: no need to prune), plus exact-ABI it87.
    modules = root / 'lib/modules' / KVER
    it87 = (modules / 'updates/it87.ko').read_bytes()
    shutil.rmtree(modules)
    run('cp', '-a', FULL_MODULES / KVER, modules)
    (modules / 'updates').mkdir(exist_ok=True)
    (modules / 'updates/it87.ko').write_bytes(it87)
    run('depmod', '-b', root, KVER)
    write(root, '/etc/fstab', f'UUID={ROOT_FS_UUID} / ext4 rw,noatime 0 1\n')
    write(root, '/etc/tenerix/root-fs-uuid', ROOT_FS_UUID + '\n')
    (root / 'etc/tenerix/dom.conf').unlink(missing_ok=True)
    write(root, '/etc/apk/repositories', 'https://dl-cdn.alpinelinux.org/alpine/v3.24/main\n'
          'https://dl-cdn.alpinelinux.org/alpine/v3.24/community\n')
    write(root, '/etc/mdadm.conf', 'AUTO -all\n')
    (root / 'media/dom').mkdir(parents=True, exist_ok=True)

    # Initramfs that assembles only the system mirror.
    write(root, '/etc/tenerix/md.conf', f"SYSTEM_MD_UUID='{SYSTEM_MD_UUID}'\nROOT_FS_UUID='{ROOT_FS_UUID}'\n"
          f"EXPECTED_MEMBERS=6\nBUILD_ID='{BUILD_ID}'\n")
    features = BUILD / 'features'
    features.mkdir()
    (features / 'mdroot.files').write_text('/bin/busybox\n/bin/sh\n/sbin/modprobe\n/sbin/mdadm\n/sbin/blkid\n'
                                           '/etc/tenerix/md.conf\n')
    (features / 'mdroot.modules').write_text('kernel/drivers/ata/ahci.ko*\nkernel/drivers/ata/libahci.ko*\n'
                                             'kernel/drivers/ata/libata.ko*\nkernel/drivers/scsi/sd_mod.ko*\n'
                                             'kernel/drivers/md/raid1.ko*\nkernel/fs/ext4\n')
    boot = BUILD / 'boot'
    (boot / 'md').mkdir(parents=True)
    run('mkinitfs', '-b', str(root) + '/', '-P', features, '-F', 'mdroot', '-i', HERE / 'init',
        '-o', boot / 'md' / f'initramfs-{KVER}', KVER)
    listing = subprocess.check_output(f'gzip -dc {boot}/md/initramfs-{KVER} | cpio -it', shell=True, text=True)
    assert 'raid1.ko' in listing and 'ahci.ko' in listing and 'raid456' not in listing and 'raid10' not in listing
    (boot / 'md' / 'SHA256SUMS').write_text(f"{sha256(boot / 'md' / f'initramfs-{KVER}')}  initramfs-{KVER}\n")
    (boot / 'SYSLINUX.CFG').write_text(SYSLINUX)

    tarball = OUT / 'tenerix-md-root.tar.gz'
    run('tar', '--numeric-owner', '-czpf', tarball, '-C', root, '.')
    boot_tar = OUT / 'tenerix-md-boot.tar'
    run('tar', '--owner=0', '--group=0', '-cf', boot_tar, '-C', boot, 'md', 'SYSLINUX.CFG')
    report = {'build_id': BUILD_ID, 'system_md_uuid': SYSTEM_MD_UUID, 'root_fs_uuid': ROOT_FS_UUID,
              'root_tar': tarball.name, 'root_tar_sha256': sha256(tarball), 'root_tar_bytes': tarball.stat().st_size,
              'boot_tar': boot_tar.name, 'boot_tar_sha256': sha256(boot_tar)}
    (OUT / 'build.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    print('MD_SYSTEM_BUILD_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
