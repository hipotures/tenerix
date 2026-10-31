#!/usr/bin/env python3
"""Build the self-contained RN426 DOM system image. Run inside the tenerix-dom-tools container.

The verified factory DOM image is the base: MBR, VBR, ldlinux and the trailing sectors stay
byte-identical; only FAT files change. The root filesystem is an ext4 file on the DOM's FAT.
Inputs outside Git: artifacts/dom-system/authorized_keys (public keys), the retained kernel APK
and it87.ko from the Alpine hardware test. Output: artifacts/dom-system/.
"""
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from domlib import Fat, run, sha256, write_generation  # noqa: E402

ROOT = Path('/work')
OUT = ROOT / 'artifacts/dom-system'
PENDRIVE = '--pendrive' in sys.argv
# Pendrive variant: same system, own MBR signature, so it never collides with the DOM.
PENDRIVE_SIGNATURE = 0x7E4E1A26
BUILD = OUT / ('build-pendrive' if PENDRIVE else 'build')
ORIGINAL = ROOT / 'artifacts/dom/readynas-rn426-original-240m.img'
ORIGINAL_SHA = '40056ae60cf7bbae0b7945797066db7ae7665fb5da1f62e009ae4d0f1355dea7'
KERNEL_APK = ROOT / 'artifacts/alpine-hardware/packages/linux-lts-6.18.58-r0.apk'
IT87 = ROOT / 'artifacts/alpine-hardware/repro-one/it87.ko'
IT87_SHA = '1155aae1cb9e794f41a719dc34ffe8df4a950c0911bc3b9d97cc4d5990235cf9'
KVER = '6.18.58-0-lts'
DOM_PARTUUID = 'fd8988d9-01'          # factory MBR signature (little-endian), partition 1
ROOT_IMAGE = 'tenerix/root.img'
ROOT_IMAGE_MIB = 150
BUILD_ID = 'dom-1'
# Atom C3538: CPUID family 6, model 0x5f, stepping 1.
CPU_SIGNATURE = 0x000506F1
NS = uuid.UUID('9b1c3f0e-6a8e-4c50-9f53-2f6f3a1d0c11')
MODULES = '''ahci sd_mod usb_storage uas xhci_pci ehci_pci ohci_pci uhci_hcd usbhid hid_generic
loop vfat nls_cp437 nls_iso8859_1 nls_utf8 ext4 ixgbe e1000 coretemp hwmon_vid i2c_i801
raid1 raid10 raid456 dm_crypt btrfs nfsd crc32c_generic aesni_intel xts cbc af_packet evdev'''.split()


def modules_closure(root):
    base = root / 'lib/modules' / KVER
    deps, by_name = {}, {}
    for line in (base / 'modules.dep').read_text().splitlines():
        path, rest = line.split(':', 1)
        deps[path] = rest.split()
        by_name[Path(path).name.split('.ko')[0].replace('-', '_')] = path
    softdeps = {}
    for line in (base / 'modules.softdep').read_text().splitlines():
        words = line.split()
        if len(words) > 2 and words[0] == 'softdep':
            softdeps[words[1].replace('-', '_')] = [w.replace('-', '_') for w in words[2:] if not w.endswith(':')]
    keep, todo, missing = set(), list(MODULES), []
    while todo:
        name = todo.pop().replace('-', '_')
        path = by_name.get(name)
        if path is None:
            missing.append(name)          # built into the kernel or absent
            continue
        if path in keep:
            continue
        keep.add(path)
        todo += [Path(d).name.split('.ko')[0] for d in deps[path]] + softdeps.get(name, [])
    return keep, sorted(set(missing))


def microcode(root, destination):
    """Extract only the update blobs for this CPU from Alpine's early microcode archive."""
    work = BUILD / 'ucode'
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    run('sh', '-c', f'cd {work} && cpio -idm < {root}/boot/intel-ucode.img')
    blob = (work / 'kernel/x86/microcode/GenuineIntel.bin').read_bytes()
    selected, offset = b'', 0
    while offset < len(blob):
        total = int.from_bytes(blob[offset + 32:offset + 36], 'little') or 2048
        data = int.from_bytes(blob[offset + 28:offset + 32], 'little') or 2000
        sigs = [int.from_bytes(blob[offset + 12:offset + 16], 'little')]
        if total > data + 48:
            ext = offset + 48 + data
            count = int.from_bytes(blob[ext:ext + 4], 'little')
            sigs += [int.from_bytes(blob[ext + 20 + 12 * i:ext + 24 + 12 * i], 'little') for i in range(count)]
        if CPU_SIGNATURE in sigs:
            selected += blob[offset:offset + total]
        offset += total
    assert selected, 'no microcode for the RN426 CPU found'
    shutil.rmtree(work)
    (work / 'kernel/x86/microcode').mkdir(parents=True)
    (work / 'kernel/x86/microcode/GenuineIntel.bin').write_bytes(selected)
    run('sh', '-c', f'cd {work} && find kernel | sort | cpio -o -H newc -R 0:0 > {destination}')
    return len(selected)


def write(root, path, text, mode=0o644):
    target = root / path.lstrip('/')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    target.chmod(mode)


def configure(root, password_hash, keys):
    run('chroot', root, '/bin/busybox', '--install', '-s')
    for d in ('etc/tenerix', 'root/.ssh', 'media/dom', 'run', 'proc', 'sys', 'dev', 'tmp'):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / 'tmp').chmod(0o1777)
    (root / 'root').chmod(0o700)
    (root / 'root/.ssh').chmod(0o700)
    write(root, '/root/.ssh/authorized_keys', keys, 0o600)
    shadow = (root / 'etc/shadow').read_text()
    (root / 'etc/shadow').write_text(re.sub(r'^root:[^:]*:', f'root:{password_hash}:', shadow, flags=re.M))
    write(root, '/etc/ssh/sshd_config', 'PermitRootLogin prohibit-password\nPasswordAuthentication no\n'
          'KbdInteractiveAuthentication no\nAuthorizedKeysFile .ssh/authorized_keys\n'
          'Subsystem sftp internal-sftp\n')
    write(root, '/etc/hostname', 'tenerix-zero\n')
    write(root, '/etc/hosts', '127.0.0.1\tlocalhost tenerix-zero\n::1\tlocalhost tenerix-zero\n')
    write(root, '/etc/inittab', '::sysinit:/sbin/openrc sysinit\n::sysinit:/sbin/openrc boot\n'
          '::wait:/sbin/openrc default\nttyS0::respawn:/sbin/getty -L 115200 ttyS0 vt100\n'
          'tty1::respawn:/sbin/getty 38400 tty1\n::ctrlaltdel:/sbin/reboot\n::shutdown:/sbin/openrc shutdown\n')
    write(root, '/etc/fstab', '/dev/loop0 / ext4 rw,noatime 0 0\n')
    # DHCP on all four ports: the network comes up on whichever one has the cable.
    write(root, '/etc/network/interfaces', 'auto lo\niface lo inet loopback\n\n'
          + ''.join(f'auto eth{i}\niface eth{i} inet dhcp\n\n' for i in (3, 0, 1, 2)))
    # Disks inserted later are never assembled automatically.
    write(root, '/etc/mdadm.conf', 'AUTO -all\n')
    write(root, '/etc/modules', 'af_packet\ncoretemp\nit87\nixgbe\ne1000\n')
    # Parameters exactly as in the supervised Alpine hardware test.
    write(root, '/etc/modprobe.d/it87.conf', 'options it87 fix_pwm_polarity=0 update_vbat=0 ignore_resource_conflict=0\n')
    write(root, '/etc/motd', 'Tenerix Zero (RN426 DOM system). Root: /dev/loop0 = /media/dom/tenerix/root.img\n'
          'Temperatures, fan speed and PWM: temps   (settings: /etc/conf.d/tenerix-fan)\n')
    # Fan keeper: PWM 80 at every boot, temperature watch, full speed on overheat (fan/).
    fan = HERE / 'fan'
    for source, target, mode in [('tenerix-fan', 'usr/local/sbin/tenerix-fan', 0o755),
                                 ('temps', 'usr/local/bin/temps', 0o755),
                                 ('tenerix-fan.start', 'etc/local.d/tenerix-fan.start', 0o755),
                                 ('tenerix-fan.stop', 'etc/local.d/tenerix-fan.stop', 0o755),
                                 ('tenerix-fan.conf', 'etc/conf.d/tenerix-fan', 0o644)]:
        (root / target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fan / source, root / target)
        (root / target).chmod(mode)
    runlevels = root / 'etc/runlevels'
    for path in runlevels.glob('*/*'):
        path.unlink()
    for level, service in [('sysinit', 'devfs'), ('sysinit', 'sysfs'), ('sysinit', 'dmesg'),
                           ('boot', 'root'), ('boot', 'hostname'), ('boot', 'bootmisc'), ('boot', 'sysctl'),
                           ('boot', 'modules'), ('boot', 'syslog'), ('default', 'networking'),
                           ('default', 'sshd'), ('default', 'local'),
                           ('shutdown', 'killprocs'), ('shutdown', 'mount-ro')]:
        (runlevels / level).mkdir(parents=True, exist_ok=True)
        (runlevels / level / service).symlink_to(f'/etc/init.d/{service}')

def main():
    assert sha256(ORIGINAL) == ORIGINAL_SHA, 'factory DOM image hash mismatch'
    signature = int.from_bytes(ORIGINAL.read_bytes()[440:444], 'little')
    assert DOM_PARTUUID == f'{signature:08x}-01', 'DOM_PARTUUID does not match the factory MBR'
    boot_partuuid = f'{PENDRIVE_SIGNATURE:08x}-01' if PENDRIVE else DOM_PARTUUID
    assert sha256(IT87) == IT87_SHA, 'it87.ko hash mismatch'
    keys = (OUT / 'authorized_keys').read_text()
    assert keys.count('sk-ssh-ed25519@openssh.com') == 3
    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir(parents=True)
    root = BUILD / 'rootfs'
    root.mkdir()

    run('apk', 'verify', KERNEL_APK)
    packages = [l for l in (HERE / 'packages.txt').read_text().splitlines() if l and not l.startswith('#')]
    run('apk', 'add', '--root', root, '--initdb', '--keys-dir', '/etc/apk/keys', '--no-scripts', '--no-cache',
        '--repository', 'https://dl-cdn.alpinelinux.org/alpine/v3.24/main',
        '--repository', 'https://dl-cdn.alpinelinux.org/alpine/v3.24/community', *packages, KERNEL_APK)
    (BUILD / 'runtime-resolved.txt').write_text(
        subprocess.check_output(['apk', '--root', str(root), 'info', '-v'], text=True))

    # Keep only the listed modules and their dependencies; add the exact-ABI it87 as an update.
    keep, missing = modules_closure(root)
    base = root / 'lib/modules' / KVER
    for module in base.rglob('*.ko*'):
        if str(module.relative_to(base)) not in keep:
            module.unlink()
    (base / 'updates').mkdir()
    shutil.copyfile(IT87, base / 'updates/it87.ko')
    run('depmod', '-b', root, KVER)
    (BUILD / 'modules.txt').write_text('\n'.join(sorted(keep)) + '\n\nbuilt-in or absent: ' + ' '.join(missing) + '\n')

    # One root password for every variant; generated once, kept outside Git.
    if (OUT / 'root-password').exists():
        password = (OUT / 'root-password').read_text().strip()
    else:
        password = secrets.token_urlsafe(12)
    password_hash = subprocess.check_output(['cryptpw', '-m', 'sha512', password], text=True).strip()
    configure(root, password_hash, keys)
    root_uuid = str(uuid.uuid5(NS, 'root-' + BUILD_ID))
    write(root, '/etc/tenerix/root-fs-uuid', root_uuid + '\n')

    gen = BUILD / 'g1'
    gen.mkdir()
    shutil.move(root / 'boot/vmlinuz-lts', gen / f'vmlinuz-{KVER}')
    ucode_bytes = microcode(root, gen / 'ucode-c3538.cpio')
    for leftover in ('intel-ucode.img', f'System.map-{KVER}'):
        (root / 'boot' / leftover).unlink(missing_ok=True)

    # Initramfs: only what is needed to mount the DOM FAT and the loop root.
    (root / 'etc/tenerix/dom.conf').write_text(
        f"DOM_PARTUUID='{boot_partuuid}'\nROOT_IMAGE='{ROOT_IMAGE}'\nROOT_FS_UUID='{root_uuid}'\nBUILD_ID='{BUILD_ID}'\n")
    features = BUILD / 'features'
    features.mkdir()
    (features / 'domsys.files').write_text('/bin/busybox\n/bin/sh\n/sbin/modprobe\n/sbin/blkid\n/etc/tenerix/dom.conf\n')
    (features / 'domsys.modules').write_text('\n'.join([
        'kernel/drivers/usb/host/xhci-pci.ko*', 'kernel/drivers/usb/host/ehci-pci.ko*', 'kernel/drivers/usb/storage',
        'kernel/drivers/scsi/sd_mod.ko*', 'kernel/fs/fat', 'kernel/fs/nls/nls_cp437.ko*',
        'kernel/fs/nls/nls_iso8859-1.ko*', 'kernel/fs/nls/nls_utf8.ko*', 'kernel/drivers/block/loop.ko*', 'kernel/fs/ext4']) + '\n')
    run('mkinitfs', '-b', str(root) + '/', '-P', features, '-F', 'domsys', '-i', HERE / 'init',
        '-o', gen / f'initramfs-{KVER}', KVER)
    (features / 'rescue.files').write_text('/bin/busybox\n/bin/sh\n')
    (features / 'rescue.modules').write_text('kernel/drivers/usb/host/xhci-pci.ko*\nkernel/drivers/usb/storage\n'
                                             'kernel/drivers/scsi/sd_mod.ko*\nkernel/drivers/ata/ahci.ko*\n')
    rescue = BUILD / 'rescue'
    rescue.mkdir()
    run('mkinitfs', '-b', str(root) + '/', '-P', features, '-F', 'rescue', '-i', HERE.parent / 'recovery-init',
        '-o', rescue / f'recovery-{KVER}', KVER)
    listing = subprocess.check_output(f'gzip -dc {gen}/initramfs-{KVER} | cpio -it', shell=True, text=True)
    assert 'nlplug-findfs' not in listing and 'raid' not in listing
    meta = write_generation(gen, BUILD_ID, f'vmlinuz-{KVER}', 'ucode-c3538.cpio', f'initramfs-{KVER}', KVER)
    (rescue / 'SHA256SUMS').write_text(f"{sha256(rescue / f'recovery-{KVER}')}  recovery-{KVER}\n")

    # Root filesystem file. Fixed size: later writes never change FAT allocation.
    image = BUILD / 'root.img'
    with image.open('xb') as f:
        f.truncate(ROOT_IMAGE_MIB * 1024 * 1024)
    run('mke2fs', '-q', '-t', 'ext4', '-F', '-L', 'tenerix-root', '-U', root_uuid, '-m', '1', '-J', 'size=4',
        '-E', 'lazy_itable_init=0,lazy_journal_init=0', '-d', root, image)
    run('e2fsck', '-fn', image)
    used = subprocess.check_output(['du', '-sm', str(root)], text=True).split()[0]

    # DOM image derived from the verified original.
    dom = OUT / ('tenerix-rn426-pendrive.img' if PENDRIVE else 'tenerix-rn426-dom-system.img')
    dom.unlink(missing_ok=True)
    shutil.copyfile(ORIGINAL, dom)
    if PENDRIVE:
        with dom.open('r+b') as f:
            f.seek(440)
            f.write(PENDRIVE_SIGNATURE.to_bytes(4, 'little'))
    fat = Fat(dom)
    for name in ('KERNEL', 'INITRD.GZ', 'KERNEL.EMG', 'INITRD.EMG', 'ROOT.TLZ', 'CSUMS.MD5', 'SYSLINUX.CFG'):
        fat.delete(name)
    for folder in ('g1', 'g0', 'rescue', 'tenerix'):
        fat.mkdir(folder)
    for slot in ('g1', 'g0'):
        for file in sorted(gen.iterdir()):
            fat.put(file, f'{slot}/{file.name}')
        fat.verify_folder(slot)
    for file in sorted(rescue.iterdir()):
        fat.put(file, f'rescue/{file.name}')
    fat.put(image, ROOT_IMAGE)
    assert hashlib.sha256(fat.read(ROOT_IMAGE)).hexdigest() == sha256(image), 'root image read-back mismatch'
    config = (HERE / 'syslinux.cfg.in').read_text()
    values = {'CURRENT_SLOT': 'g1', 'PREVIOUS_SLOT': 'g0', 'CURRENT_BUILD': BUILD_ID, 'PREVIOUS_BUILD': BUILD_ID,
              'RESCUE_INITRAMFS': f'recovery-{KVER}'}
    for prefix in ('CURRENT', 'PREVIOUS'):
        values.update({f'{prefix}_KERNEL': meta['kernel'], f'{prefix}_UCODE': meta['ucode'],
                       f'{prefix}_INITRAMFS': meta['initramfs']})
    for key, value in values.items():
        config = config.replace(f'@{key}@', value)
    assert '@' not in config
    fat.put_bytes(config.encode(), 'SYSLINUX.CFG')
    free = fat.free_bytes()
    a, b = ORIGINAL.read_bytes(), dom.read_bytes()
    assert len(a) == len(b) and a[:440] + a[444:16896] == b[:440] + b[444:16896], 'MBR/gap/VBR changed'
    assert int.from_bytes(b[440:444], 'little') == int(boot_partuuid[:8], 16)
    assert a[458752 * 512:] == b[458752 * 512:], 'trailing sectors changed'
    for name in ('ldlinux.sys', 'ldlinux.c32'):
        assert Fat(ORIGINAL).read(name) == fat.read(name)

    (OUT / 'root-password').write_text(password + '\n')
    (OUT / 'root-password').chmod(0o600)
    digest = sha256(dom)
    (OUT / (dom.name + '.sha256')).write_text(f'{digest}  {dom.name}\n')
    report = {'image': dom.name, 'bytes': dom.stat().st_size, 'sha256': digest, 'build_id': BUILD_ID,
              'kernel': KVER, 'root_fs_uuid': root_uuid, 'root_image_mib': ROOT_IMAGE_MIB,
              'rootfs_used_mib': int(used), 'fat_free_bytes': free, 'microcode_bytes': ucode_bytes,
              'kept_modules': len(keep), 'it87_sha256': IT87_SHA}
    (OUT / ('build-pendrive.json' if PENDRIVE else 'build.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    print('DOM_SYSTEM_BUILD_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
