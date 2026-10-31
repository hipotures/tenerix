#!/usr/bin/env python3
"""Full disposable QEMU test sequence. Run inside the tenerix-dom-tools container.

Every test image is a copy of the Tenerix DOM image below artifacts/dom; the fixture disks are
the six synthetic sparse members. Nothing here can reach the NAS or a physical device.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys

from domlib import OUT, Fat, sha256

HERE = Path(__file__).resolve().parent
DOM = OUT / 'tenerix-rn426-alpine-boot.img'
TESTS = OUT / 'test-images'


def step(*args):
    print('==>', *args, flush=True)
    subprocess.run([sys.executable, *map(str, args)], check=True, cwd=HERE)


def copy(name, source=DOM):
    TESTS.mkdir(exist_ok=True)
    target = TESTS / name
    target.unlink(missing_ok=True)
    shutil.copyfile(source, target)
    return target


def main():
    step('qemu.py', 'fixture')
    step('decoy-hashes.py', '--write', OUT / 'decoys-before.json')
    step('qemu.py', 'boot', 'current', '--reboot')
    step('qemu.py', 'boot', 'previous', '--select', 'previous', '--slot', 'g0', '--build', 'proto-a')
    step('qemu.py', 'recovery', 'recovery')

    # Broken 1: current kernel missing -> SYSLINUX ONERROR falls back to previous, unattended.
    broken = copy('broken-kernel.img')
    Fat(broken).delete('g1/vmlinuz-6.18.58-0-lts')
    step('qemu.py', 'boot', 'broken-kernel', '--dom', broken, '--slot', 'g0', '--build', 'proto-a')

    # Broken 2: current initramfs truncated: the kernel loads and the boot fails. After a power
    # cycle the operator selects the previous generation over the serial console.
    broken = copy('broken-initramfs.img')
    fat = Fat(broken)
    good = fat.read('g1/initramfs-6.18.58-0-lts')
    fat.delete('g1/initramfs-6.18.58-0-lts')
    fat.put_bytes(good[:len(good) // 3], 'g1/initramfs-6.18.58-0-lts')
    step('qemu.py', 'boot', 'broken-initramfs', '--dom', broken, '--fail-first', '--select', 'previous',
         '--slot', 'g0', '--build', 'proto-a')

    # Update: new generation goes into the inactive slot g0; g1 becomes previous.
    generation = OUT / 'generations/proto-c'
    if generation.exists():
        shutil.rmtree(generation)
    step('build.py', 'generation', 'proto-c')
    updated = copy('updated.img')
    step('dom-update.py', 'install', updated, generation)
    step('qemu.py', 'boot', 'updated-current', '--dom', updated, '--slot', 'g0', '--build', 'proto-c')
    step('qemu.py', 'boot', 'updated-previous', '--dom', updated, '--select', 'previous',
         '--slot', 'g1', '--build', 'proto-b')
    # Kernel rollback is a configuration-only slot flip.
    rolled = copy('rolled-back.img', updated)
    step('dom-update.py', 'rollback', rolled)
    step('qemu.py', 'boot', 'rolled-back', '--dom', rolled, '--slot', 'g1', '--build', 'proto-b')

    # Last: degraded boot leaves member 6 stale, so it must not precede the 6/6 checks.
    step('qemu.py', 'boot', 'degraded', '--degraded')
    step('decoy-hashes.py', OUT / 'decoys-before.json')

    names = ['current', 'previous', 'recovery', 'broken-kernel', 'broken-initramfs',
             'updated-current', 'updated-previous', 'rolled-back', 'degraded']
    summary = {n: json.loads((OUT / 'logs' / f'{n}.json').read_text()) for n in names}
    for result in summary.values():
        result.pop('command')
        assert result['passed'], result['name']
    images = [DOM, OUT / 'readynas-rn426-original-240m.img', *sorted(TESTS.glob('*.img'))]
    summary['sha256'] = {str(p.relative_to(OUT)): sha256(p) for p in images}
    (OUT / 'logs/summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('TEST_SUITE_PASSED', flush=True)


if __name__ == '__main__':
    main()
