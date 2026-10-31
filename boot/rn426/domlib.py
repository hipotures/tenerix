"""Shared helpers for DOM image files. Never accepts block devices or paths outside artifacts/dom."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

ROOT = Path('/work')
OUT = ROOT / 'artifacts/dom'
DOM_BYTES = 251658240
FAT_OFFSET = 16384
SLOTS = ('g0', 'g1')
# Space that must remain free on the FAT partition after any staged write.
MARGIN_BYTES = 32 * 1024 * 1024
TEMPLATE = Path(__file__).with_name('syslinux.cfg.in')


def run(*args, **kwargs):
    print('+', *map(str, args), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def kernel_release(bzimage):
    """Read the release string embedded in an x86 bzImage setup header."""
    data = Path(bzimage).read_bytes()
    assert data[0x202:0x206] == b'HdrS', 'not an x86 bzImage'
    offset = int.from_bytes(data[0x20E:0x210], 'little') + 0x200
    return data[offset:data.index(b'\0', offset)].decode().split()[0]


def checked_image(path):
    """Only regular, non-symlinked, exact-size image files below artifacts/dom."""
    path = Path(path)
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_size != DOM_BYTES:
        raise SystemExit(f'{path}: not a regular {DOM_BYTES}-byte DOM image file')
    if not any(path.resolve().is_relative_to(d.resolve()) for d in (OUT, ROOT / 'artifacts/dom-system', ROOT / 'artifacts/md-system')):
        raise SystemExit(f'{path}: DOM image must reside below {OUT}, artifacts/dom-system or artifacts/md-system')
    return path


class Fat:
    """mtools access to the FAT16 partition inside a checked DOM image file."""

    def __init__(self, image):
        self.spec = f'{checked_image(image)}@@{FAT_OFFSET}'

    def ls(self, folder):
        try:
            text = subprocess.check_output(['mdir', '-b', '-i', self.spec, f'::{folder}'],
                                           text=True, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            return None
        return sorted(line.rstrip('/').rsplit('/', 1)[-1] for line in text.splitlines() if line)

    def read(self, name):
        return subprocess.check_output(['mtype', '-i', self.spec, f'::{name}'])

    def put(self, source, name):
        run('mcopy', '-i', self.spec, source, f'::{name}')

    def put_bytes(self, data, name):
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(data); tmp.flush()
            self.put(tmp.name, name)

    def delete(self, name):
        run('mdel', '-i', self.spec, f'::{name}')

    def rename(self, old, new):
        run('mren', '-i', self.spec, f'::{old}', f'::{new}')

    def mkdir(self, folder):
        run('mmd', '-i', self.spec, f'::{folder}')

    def free_bytes(self):
        text = subprocess.check_output(['mdir', '-a', '-i', self.spec, '::'], text=True)
        return int(re.search(r'([\d ]+) bytes free', text).group(1).replace(' ', '').replace(' ', ''))

    def verify_folder(self, folder):
        """Read back every file listed in the folder's SHA256SUMS through the FAT layer."""
        sums = self.read(f'{folder}/SHA256SUMS').decode()
        names = []
        for line in sums.splitlines():
            digest, name = line.split(maxsplit=1)
            if hashlib.sha256(self.read(f'{folder}/{name}')).hexdigest() != digest:
                raise SystemExit(f'{folder}/{name}: read-back hash mismatch')
            names.append(name)
        assert set(self.ls(folder)) == set(names) | {'SHA256SUMS'}, f'{folder}: unlisted files'
        return json.loads(self.read(f'{folder}/generation.json'))


def write_generation(folder, build_id, kernel, ucode, initramfs, kver):
    """Finalize a local generation directory: generation.json plus SHA256SUMS over all files."""
    folder = Path(folder)
    assert kernel_release(folder / kernel) == kver, 'kernel release does not match module tree'
    meta = {'build_id': build_id, 'kernel_release': kver, 'kernel': kernel,
            'ucode': ucode, 'initramfs': initramfs}
    (folder / 'generation.json').write_text(json.dumps(meta, indent=2) + '\n')
    files = sorted(p.name for p in folder.iterdir() if p.name != 'SHA256SUMS')
    (folder / 'SHA256SUMS').write_text(''.join(f'{sha256(folder / n)}  {n}\n' for n in files))
    return meta


def render_config(current_slot, current, previous_slot, previous, rescue):
    values = {'CURRENT_SLOT': current_slot, 'PREVIOUS_SLOT': previous_slot,
              'RESCUE_KERNEL': rescue['kernel'], 'RESCUE_INITRAMFS': rescue['initramfs']}
    for prefix, meta in (('CURRENT', current), ('PREVIOUS', previous)):
        for key in ('kernel', 'ucode', 'initramfs'):
            values[f'{prefix}_{key.upper()}'] = meta[key]
        values[f'{prefix}_BUILD'] = meta['build_id']
    text = TEMPLATE.read_text()
    for key, value in values.items():
        assert re.fullmatch(r'[A-Za-z0-9._-]+', value), f'unsafe config value {value!r}'
        text = text.replace(f'@{key}@', value)
    assert '@' not in text, 'unresolved template placeholder'
    return text.encode()


def current_slot(fat):
    config = fat.read('SYSLINUX.CFG').decode()
    match = re.search(r'^LABEL current\n\s+LINUX /(g[01])/', config, re.M)
    assert match, 'cannot determine current slot from SYSLINUX.CFG'
    return match.group(1)


def replace_config(fat, data):
    """Stage SYSLINUX.NEW, verify it, then swap it in. The delete/rename window is documented."""
    if 'SYSLINUX.NEW' in fat.ls(''):
        fat.delete('SYSLINUX.NEW')
    fat.put_bytes(data, 'SYSLINUX.NEW')
    assert fat.read('SYSLINUX.NEW') == data, 'staged config read-back mismatch'
    fat.delete('SYSLINUX.CFG')
    fat.rename('SYSLINUX.NEW', 'SYSLINUX.CFG')
    assert fat.read('SYSLINUX.CFG') == data, 'active config read-back mismatch'
