#!/usr/bin/env python3
"""Hash only synthetic decoy partitions in regular local fixture files."""
import hashlib
import json
from pathlib import Path
import sys

out = Path('/work/artifacts/dom')
result = {}
for i in range(1, 7):
    path = out / f'system-member-{i}.raw'
    assert path.is_file() and not path.is_symlink() and path.stat().st_size == 4563402752
    with path.open('rb') as f:
        for partition, start, sectors in [(2, 8390656, 131072), (3, 8521728, 262144)]:
            f.seek(start * 512)
            digest = hashlib.sha256()
            remaining = sectors * 512
            while remaining:
                data = f.read(min(remaining, 1048576))
                assert data
                remaining -= len(data); digest.update(data)
            result[f'{path.name}:p{partition}'] = digest.hexdigest()
if sys.argv[1:2] == ['--write']:
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n')
elif len(sys.argv) == 2:
    expected = json.loads(Path(sys.argv[1]).read_text())
    assert result == expected, 'Synthetic decoy content changed'
print(json.dumps(result, indent=2))
