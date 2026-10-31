#!/usr/bin/env python3
"""Install a built generation into the inactive slot of a DOM *image file*, or flip slots.

  dom-update.py install IMAGE GENERATION_DIR   stage into inactive slot, verify, then activate
  dom-update.py rollback IMAGE                 make the previous slot current (config-only)
  dom-update.py status IMAGE                   verify both slots and print the layout

The active slot is never written. Every staged file is read back through the FAT layer and
compared with the generation's SHA256SUMS before SYSLINUX.CFG is switched. Only image files
below artifacts/dom are accepted; this prototype never writes a physical device.
"""
import argparse
import json
from pathlib import Path

from domlib import MARGIN_BYTES, SLOTS, Fat, current_slot, render_config, replace_config, sha256


def other(slot):
    return SLOTS[1 - SLOTS.index(slot)]


def status(fat):
    active = current_slot(fat)
    layout = {'current': active, 'previous': other(active), 'free_bytes': fat.free_bytes()}
    for slot in SLOTS + ('rescue',):
        layout[slot] = fat.verify_folder(slot)
    return layout


def install(fat, source):
    source = Path(source)
    meta = json.loads((source / 'generation.json').read_text())
    sums = (source / 'SHA256SUMS').read_text().splitlines()
    files = []
    for line in sums:
        digest, name = line.split(maxsplit=1)
        assert '/' not in name and sha256(source / name) == digest, f'{name}: local hash mismatch'
        files.append(name)
    assert {meta['kernel'], meta['ucode'], meta['initramfs'], 'generation.json'} <= set(files)
    layout = status(fat)
    active, target = layout['current'], layout['previous']
    if meta['build_id'] in (layout[active]['build_id'], layout[target]['build_id']):
        raise SystemExit(f"build {meta['build_id']} is already installed")
    incoming = sum((source / n).stat().st_size for n in files + ['SHA256SUMS'])
    reclaimed = sum(len(fat.read(f'{target}/{n}')) for n in fat.ls(target))
    remaining = layout['free_bytes'] + reclaimed - incoming
    print(json.dumps({'active': active, 'target': target, 'incoming': incoming,
                      'reclaimed': reclaimed, 'free_after': remaining}), flush=True)
    if remaining < MARGIN_BYTES:
        raise SystemExit('insufficient FAT space margin; nothing changed')
    # From here only the inactive slot is touched; the active slot stays bootable throughout.
    for name in fat.ls(target):
        fat.delete(f'{target}/{name}')
    for name in [n for n in files if n != 'generation.json'] + ['generation.json', 'SHA256SUMS']:
        fat.put(source / name, f'{target}/{name}')
    staged = fat.verify_folder(target)
    assert staged == meta
    replace_config(fat, render_config(target, staged, active, layout[active], layout['rescue']))
    return status(fat)


def rollback(fat):
    layout = status(fat)
    active, previous = layout['current'], layout['previous']
    replace_config(fat, render_config(previous, layout[previous], active, layout[active], layout['rescue']))
    return status(fat)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['install', 'rollback', 'status'])
    parser.add_argument('image')
    parser.add_argument('generation', nargs='?')
    args = parser.parse_args()
    fat = Fat(args.image)
    if args.command == 'install':
        if not args.generation:
            parser.error('install needs GENERATION_DIR')
        result = install(fat, args.generation)
    elif args.command == 'rollback':
        result = rollback(fat)
    else:
        result = status(fat)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
