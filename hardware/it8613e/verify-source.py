#!/usr/bin/env python3
"""Check that the backport differs from accepted upstream only by IT8689 support."""
from pathlib import Path
import hashlib
import subprocess
import tempfile

root = Path(__file__).resolve().parent
subprocess.run(['sha256sum', '--check', 'SOURCES.sha256'], cwd=root, check=True)
with tempfile.TemporaryDirectory(prefix='it8613-source-') as directory:
    generated = Path(directory) / 'it87.c'
    generated.write_bytes((root / 'upstream/linux-6.12.107-it87.c').read_bytes())
    with (root / 'patches/0001-backport-it8613e-linux-6.12.107.patch').open('rb') as patch:
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-d', directory],
                       stdin=patch, check=True)
    result = generated.read_text()
    expected_hash = 'ccdd098144f8ef99bc40a183c46e1c889e5987c076f6f13478a913307212085f'
    if hashlib.sha256(generated.read_bytes()).hexdigest() != expected_hash:
        raise SystemExit('Unexpected generated source hash')

reference = (root / 'upstream/linux-it8613e-upstream.c').read_text()
reference = reference.replace(' *            IT8689E  Super I/O chip w/LPC interface\n', '')
reference = reference.replace(', it8689,', ',')
reference = reference.replace('#define IT8689E_DEVID 0x8689\n', '')
start = reference.index('\t[it8689] = {')
end = reference.index('\t[it87952] = {', start)
reference = reference[:start] + reference[end:]
reference = reference.replace('\tcase IT8689E_DEVID:\n\t\tsio_data->type = it8689;\n\t\tbreak;\n', '')
start = reference.index('\t} else if (sio_data->type == it8689) {')
end = reference.index('\t} else if (sio_data->type == it8622) {', start)
reference = reference[:start] + reference[end:]
if result != reference:
    raise SystemExit('Difference beyond the deliberately omitted IT8689 support')
print('PASS: clean zero-fuzz patch; expected source hash; exact upstream minus IT8689.')
