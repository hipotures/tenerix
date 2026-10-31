#!/usr/bin/env python3
"""Local-container build. Only regular files below artifacts/dom are writable.

  build.py image [--replace]   rootfs, fixture input, slots g0/g1, rescue, Tenerix DOM image
  build.py generation BUILD_ID new kernel/initramfs generation for dom-update.py
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from domlib import OUT, ROOT, Fat, render_config, run, sha256, write_generation

BUILD = OUT / 'build'
SOURCE_SHA = '40056ae60cf7bbae0b7945797066db7ae7665fb5da1f62e009ae4d0f1355dea7'
KVER = '6.18.58-0-lts'
UCODE = 'ucode-20260812.cpio'
NS = uuid.UUID('6080a5c7-c1a5-45ee-8d99-72ad85bc674e')
# Initial image: two distinct builds of identical inputs, so tests can tell the slots apart.
INITIAL = {'g0': 'proto-a', 'g1': 'proto-b'}


def md_uuid(name):
    h = uuid.uuid5(NS, name).hex
    return ':'.join(h[i:i + 8] for i in range(0, 32, 8))


def conf(build_id):
    return (f"SYSTEM_MD_UUID='{md_uuid('system')}'\n"
            + "SYSTEM_PARTUUIDS='" + ' '.join(str(uuid.uuid5(NS, f'member-{i}-part-1')) for i in range(6)) + "'\n"
            + f"ROOT_FS_UUID='{uuid.uuid5(NS, 'rootfs')}'\nBUILD_ID='{build_id}'\n")


def initramfs(root, build_id, init, destination, fixture=False):
    feature = BUILD / 'features'
    feature.mkdir(exist_ok=True)
    (feature / 'tenerix.files').write_text('/bin/busybox\n/bin/sh\n/sbin/modprobe\n/sbin/mdadm\n/sbin/blkid\n/etc/mdadm.conf\n/etc/tenerix/root.conf\n')
    (feature / 'tenerix.modules').write_text('\n'.join([
        'kernel/drivers/md/raid1.ko*', 'kernel/fs/ext4',
        'kernel/drivers/ata/ahci.ko*', 'kernel/drivers/scsi/sd_mod.ko*',
        'kernel/drivers/usb/host/xhci-pci.ko*', 'kernel/drivers/usb/storage',
        'kernel/drivers/block/virtio_blk.ko*', 'kernel/drivers/virtio/virtio_pci.ko*']) + '\n')
    (feature / 'fixture.files').write_text('/sbin/mke2fs\n')
    (feature / 'fixture.modules').write_text('kernel/drivers/md/raid*.ko*\nkernel/net/9p\nkernel/fs/9p\n')
    (root / 'etc/tenerix/root.conf').write_text(conf(build_id))
    try:
        run('mkinitfs', '-b', str(root) + '/', '-P', feature, '-F',
            'tenerix fixture' if fixture else 'tenerix', '-i', init, '-o', destination, KVER)
    finally:
        (root / 'etc/tenerix/root.conf').write_text(conf('rootfs'))
    # Audit the generated archive: no automatic discovery utility is included.
    listing = subprocess.check_output(f'gzip -dc {destination} | cpio -it', shell=True, text=True)
    assert 'nlplug-findfs' not in listing
    (BUILD / (destination.name + f'.{build_id}.listing')).write_text(listing)


def generation(root, build_id, folder):
    """Kernel, microcode and initramfs from one rootfs, so modules always match the kernel."""
    if folder.exists():
        raise SystemExit(f'{folder} exists: generations are immutable once built')
    assert (root / 'lib/modules' / KVER / 'modules.dep').is_file(), 'module tree missing'
    folder.mkdir(parents=True)
    shutil.copyfile(root / 'boot/vmlinuz-lts', folder / f'vmlinuz-{KVER}')
    microcode = root / 'boot/intel-ucode.img'
    assert microcode.is_file(), 'Expected packaged early Intel microcode archive'
    shutil.copyfile(microcode, folder / UCODE)
    initramfs(root, build_id, ROOT / 'boot/rn426/init', folder / f'initramfs-{KVER}')
    return write_generation(folder, build_id, f'vmlinuz-{KVER}', UCODE, f'initramfs-{KVER}', KVER)


def image(replace):
    os.chdir(ROOT)
    original = OUT / 'readynas-rn426-original-240m.img'
    assert original.is_file() and original.stat().st_size == 251658240
    assert sha256(original) == SOURCE_SHA
    BUILD.mkdir(exist_ok=True)
    (BUILD / 'root.conf').write_text(conf('rootfs'))
    (BUILD / 'network-mac').write_text('52:54:00:42:60:04\n')
    if not (OUT / 'test-admin').exists():
        run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', OUT / 'test-admin')
    root = BUILD / 'rootfs'
    if not root.exists():
        run('sh', ROOT / 'boot/rn426/build-root.sh')
    fixture = conf('fixture') + f"SWAP_MD_UUID='{md_uuid('swap-decoy')}'\nDATA_MD_UUID='{md_uuid('data-decoy')}'\n"
    (BUILD / 'fixture.conf').write_text(fixture)
    layout = {'system_md_uuid': md_uuid('system'), 'swap_decoy_uuid': md_uuid('swap-decoy'),
              'data_decoy_uuid': md_uuid('data-decoy'), 'root_fs_uuid': str(uuid.uuid5(NS, 'rootfs')),
              'disk_bytes': 4563402752, 'members': []}
    for i, letter in enumerate('abcdef'):
        disk = OUT / f'system-member-{i + 1}.raw'
        if not disk.exists():
            with disk.open('xb') as f:
                f.truncate(layout['disk_bytes'])
            table = (f'label: gpt\nlabel-id: {uuid.uuid5(NS, f"disk-{i}")}\nunit: sectors\n'
                     + '\n'.join(f'start={start}, size={size}, type=A19D880F-05FC-4D3B-A006-743F0F84911E, uuid={uuid.uuid5(NS, f"member-{i}-part-{n}")}, name="tenerix-{name}"'
                        for n, start, size, name in [(1, 2048, 8388608, 'system'), (2, 8390656, 131072, 'swap-decoy'), (3, 8521728, 262144, 'data-decoy')]) + '\n')
            run('sfdisk', '--no-reread', '--no-tell-kernel', disk, input=table, text=True)
        layout['members'].append({'image': disk.name, 'serial': f'TENERIX-FIXTURE-{letter}',
                                  'system_partuuid': str(uuid.uuid5(NS, f'member-{i}-part-1'))})
    (OUT / 'fixture-layout.json').write_text(json.dumps(layout, indent=2) + '\n')
    for folder in [BUILD / s for s in INITIAL] + [BUILD / 'rescue']:
        if folder.exists():
            shutil.rmtree(folder)
    metas = {slot: generation(root, build_id, BUILD / slot) for slot, build_id in INITIAL.items()}
    rescue = BUILD / 'rescue'
    rescue.mkdir()
    shutil.copyfile(root / 'boot/vmlinuz-lts', rescue / f'vmlinuz-{KVER}')
    initramfs(root, 'recovery', ROOT / 'boot/rn426/recovery-init', rescue / f'recovery-{KVER}')
    rescue_meta = write_generation(rescue, 'recovery', f'vmlinuz-{KVER}', None, f'recovery-{KVER}', KVER)
    if (BUILD / 'fixture-initramfs').exists():
        (BUILD / 'fixture-initramfs').unlink()
    initramfs(root, 'fixture', ROOT / 'boot/rn426/fixture-init', BUILD / 'fixture-initramfs', fixture=True)
    run('tar', '--sort=name', '--mtime=@1793404800', '--owner=0', '--group=0',
        '--numeric-owner', '-czf', BUILD / 'rootfs.tar.gz', '-C', root, '.')
    working = OUT / 'tenerix-rn426-alpine-boot.img'
    if working.exists():
        if not replace:
            raise SystemExit('Working DOM image already exists: pass --replace to rebuild it')
        working.unlink()
    shutil.copyfile(original, working)
    fat = Fat(working)
    # Remove every factory kernel/initramfs/root payload and its unsafe boot paths.
    for name in ('KERNEL', 'INITRD.GZ', 'KERNEL.EMG', 'INITRD.EMG', 'ROOT.TLZ', 'CSUMS.MD5', 'SYSLINUX.CFG'):
        fat.delete(name)
    for folder in ('g0', 'g1', 'rescue'):
        fat.mkdir(folder)
        for file in sorted((BUILD / folder).iterdir()):
            fat.put(file, f'{folder}/{file.name}')
        fat.verify_folder(folder)
    fat.put_bytes(render_config('g1', metas['g1'], 'g0', metas['g0'], rescue_meta), 'SYSLINUX.CFG')
    run('mdir', '-a', '-i', fat.spec, '::')
    # The loader code and allocation must remain untouched; file hashes plus sector checks follow.
    assert working.stat().st_size == original.stat().st_size
    for name in ('ldlinux.sys', 'ldlinux.c32'):
        assert Fat(original).read(name) == fat.read(name)
    a, b = original.read_bytes(), working.read_bytes()
    assert a[:16384 + 512] == b[:16384 + 512], 'MBR/gap/VBR changed'
    assert a[458752 * 512:] == b[458752 * 512:], 'Trailing 16 MiB changed'
    print('DOM_BUILD_COMPLETE', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('image').add_argument('--replace', action='store_true',
                                         help='delete and rebuild the derived Tenerix DOM image')
    sub.add_parser('generation').add_argument('build_id')
    args = parser.parse_args()
    if args.command == 'image':
        image(args.replace)
    else:
        assert all(c.isalnum() or c in '.-' for c in args.build_id)
        meta = generation(BUILD / 'rootfs', args.build_id, OUT / 'generations' / args.build_id)
        print(json.dumps(meta, indent=2))


if __name__ == '__main__':
    main()
