#!/usr/bin/env python3
"""Create a version-pinned deployment bundle; never installs or loads it."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
manifest = json.loads((HERE / 'compatibility.json').read_text())
module = ROOT / 'artifacts/alpine-hardware/repro-one/it87.ko'
if hashlib.sha256(module.read_bytes()).hexdigest() != manifest['module_sha256']:
    raise SystemExit('Candidate module checksum mismatch')
panel = ROOT / 'hardware/front-panel'
pin = json.loads((panel / 'provenance.json').read_text())
files = {
    'module/it87.ko': module.read_bytes(),
    'module/COPYING': (HERE.parent / 'COPYING').read_bytes(),
    'compatibility.json': (HERE / 'compatibility.json').read_bytes(),
    'panel/panel.py': (panel / 'panel.py').read_bytes(),
    'panel/provenance.json': (panel / 'provenance.json').read_bytes(),
    'panel/LICENSE': (panel / 'LICENSE').read_bytes(),
}
for name, expected in pin['runtime_sha256'].items():
    data = (panel / '.upstream' / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f'Unreviewed panel source: {name}')
    files['panel/.upstream/' + name] = data
files['SHA256SUMS'] = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                              for name, data in sorted(files.items())).encode()
out = ROOT / 'artifacts/alpine-hardware/tenerix-rn426-6.18.58-0-lts.tar.gz'
with out.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as zipped:
    with tarfile.open(fileobj=zipped, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
sha = hashlib.sha256(out.read_bytes()).hexdigest()
out.with_name(out.name + '.sha256').write_text(sha + '  ' + out.name + '\n')
print(out)
print(out.stat().st_size, sha)
