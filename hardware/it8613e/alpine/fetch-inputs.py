#!/usr/bin/env python3
"""Fetch exact public kernel inputs locally; apk verifies signatures in the builder.

Checksums pin reviewed bytes, not a substitute for Alpine signature validation.
"""
import hashlib
from pathlib import Path
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'artifacts/alpine-hardware/packages'
BASE = 'https://mirrors.huaweicloud.com/repository/alpine/v3.24/main/x86_64/'
FILES = {
    'linux-lts-dev-6.18.58-r0.apk': '10748bf4d33e265c74e20458a0c86a30bc932771f653b5a3dac22b5ebadc0f77',
    'linux-lts-6.18.58-r0.apk': 'af399fba75cafb2940fc2853eb73ba2289aa463228f33541cd3010334a30992b',
}
OUT.mkdir(parents=True, exist_ok=True)
for name, expected in FILES.items():
    destination = OUT / name
    if destination.exists():
        data = destination.read_bytes()
    else:
        with urllib.request.urlopen(BASE + name, timeout=120) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f'Checksum mismatch: {name}')
    destination.write_bytes(data)
    print(name, expected)

# Archive the exact reviewed dependency closure, without relying on a moving index.
ARCHIVES = ROOT / 'artifacts/alpine-hardware/builder-apks'
ARCHIVES.mkdir(parents=True, exist_ok=True)
for line in (Path(__file__).with_name('builder-apks.sha256')).read_text().splitlines():
    expected, name = line.split()
    destination = ARCHIVES / name
    if destination.exists():
        data = destination.read_bytes()
    elif name in FILES:
        data = (OUT / name).read_bytes()
    else:
        data = None
        for repository in ('main', 'community'):
            url = f'https://dl-cdn.alpinelinux.org/alpine/v3.24/{repository}/x86_64/{name}'
            try:
                with urllib.request.urlopen(url, timeout=120) as response:
                    data = response.read()
                break
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
        if data is None:
            raise SystemExit(f'Exact package no longer mirrored: {name}; use retained archive')
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f'Checksum mismatch: {name}')
    if not destination.exists():
        destination.write_bytes(data)
print('Exact builder archive closure verified')
