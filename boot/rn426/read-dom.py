#!/usr/bin/env python3
"""Read-only NAS helper. Stream over SSH; never creates a remote file."""
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys

USB = Path('/sys/bus/usb/devices/1-2').resolve(strict=True)
assert (USB / 'idVendor').read_text().strip() == '13fe'
assert (USB / 'idProduct').read_text().strip() == '5200'
blocks = list(USB.glob('1-2:*/host*/target*/*/block/*'))
assert len(blocks) == 1, 'Ambiguous DOM block identity'
block = blocks[0]
assert int((block / 'size').read_text()) == 491520
assert int((block / 'queue/logical_block_size').read_text()) == 512
partitions = [p for p in block.iterdir() if (p / 'partition').exists()]
assert len(partitions) == 1
part = partitions[0]
assert int((part / 'partition').read_text()) == 1
assert int((part / 'start').read_text()) == 32
assert int((part / 'size').read_text()) == 458720
mounts = [line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()]
matching = [m for m in mounts if m[4] == '/mnt/internal']
assert len(matching) == 1, 'Expected existing mount at /mnt/internal'
m = matching[0]
assert m[2] == (part / 'dev').read_text().strip()
assert 'ro' in m[5].split(',') and m[m.index('-') + 1] == 'vfat'
for entry in mounts:
    if entry[2] in ((block / 'dev').read_text().strip(), (part / 'dev').read_text().strip()):
        assert 'ro' in entry[5].split(','), 'DOM has a writable mount'
node = Path('/dev') / block.name
fd = os.open(node, os.O_RDONLY | os.O_CLOEXEC)
with os.fdopen(fd, 'rb', buffering=0) as source:
    info = os.fstat(source.fileno())
    assert stat.S_ISBLK(info.st_mode)
    assert f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}' == (block / 'dev').read_text().strip()
    mbr = source.read(512)
    assert mbr[510:] == b'\x55\xaa'
    entry = mbr[446:462]
    assert entry[0] == 0x80 and entry[4] == 6
    assert struct.unpack_from('<II', entry, 8) == (32, 458720)
    assert not any(mbr[462:510]), 'Unexpected additional MBR partitions'
    source.seek(0)
    mode = sys.argv[1]
    if mode == 'info':
        print(json.dumps({'usb': '1-2', 'vendor_product': '13fe:5200', 'device': str(node),
                          'bytes': 251658240, 'logical_sector': 512,
                          'partition_start': 32, 'partition_sectors': 458720,
                          'mount': '/mnt/internal', 'mount_options': m[5],
                          'mbr_sha256': hashlib.sha256(mbr).hexdigest()}))
    else:
        assert mode in ('hash', 'stream')
        digest = hashlib.sha256()
        remaining = 251658240
        while remaining:
            data = source.read(min(1048576, remaining))
            assert data, 'Short DOM read'
            remaining -= len(data)
            if mode == 'stream':
                sys.stdout.buffer.write(data)
            else:
                digest.update(data)
        assert source.read(1) == b'', 'Unexpected DOM length'
        if mode == 'hash':
            print(digest.hexdigest())
