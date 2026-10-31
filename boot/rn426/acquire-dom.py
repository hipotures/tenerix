#!/usr/bin/env python3
"""Acquire only the explicitly identified read-only DOM, with no overwrite."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/dom'
HELPER = Path(__file__).with_name('read-dom.py').read_bytes()
SSH = ['ssh', '-F', str(Path.home() / '.ssh/config'), '-o', 'IdentitiesOnly=yes',
       '-o', 'BatchMode=yes', '-o', 'ControlPath=/tmp/rn426-dom-ssh', 'root@192.168.1.115']


def remote(mode, output=None):
    return subprocess.run(SSH + ['python3', '-', mode], input=HELPER,
                          stdout=output or subprocess.PIPE, check=True).stdout


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    image = OUT / 'readynas-rn426-original-240m.img'
    metadata = json.loads(remote('info'))
    before = remote('hash').decode().strip()
    # O_EXCL prevents overwriting a pre-existing backup, even on interrupted reruns.
    fd = os.open(image, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as target:
        remote('stream', target)
        target.flush()
        os.fsync(target.fileno())
    assert image.stat().st_size == metadata['bytes']
    after = remote('hash').decode().strip()
    local = hashlib.sha256(image.read_bytes()).hexdigest()
    assert before == after == local, 'Source consistency/hash mismatch: STOP'
    metadata.update({'sha256': local, 'source_before': before, 'source_after': after,
                     'acquired_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     'method': 'O_RDONLY complete source, SSH streaming, pre/post source hashes'})
    (OUT / (image.name + '.sha256')).write_text(local + '  ' + image.name + '\n')
    (OUT / 'acquisition.json').write_text(json.dumps(metadata, indent=2) + '\n')
    image.chmod(0o400)
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
