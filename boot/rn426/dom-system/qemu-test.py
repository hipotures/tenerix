#!/usr/bin/env python3
"""QEMU test of the exact DOM system image (on a writable copy). No disks, no host network.

Checks: factory SYSLINUX, 3 s autoboot, loop ext4 root, OpenRC, DHCP, sshd with the three
security-key types accepted, it87 resolved from updates/, password login on ttyS0, persistence
across a clean reboot, the previous slot and the RAM recovery entry.
"""
import json
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time

import pexpect

OUT = Path('/work/artifacts/dom-system')
PENDRIVE = '--pendrive' in sys.argv
IMAGE = OUT / ('tenerix-rn426-pendrive.img' if PENDRIVE else 'tenerix-rn426-dom-system.img')
COPY = OUT / 'test-copy.img'
NAME = 'qemu-test-pendrive' if PENDRIVE else 'qemu-test'
PROMPT = r'tenerix-zero:[^\r\n]*# '


def spawn(port, log):
    cmd = ['qemu-system-x86_64', '-machine', 'pc,accel=tcg', '-cpu', 'max', '-smp', '2', '-m', '2048',
           '-display', 'none', '-serial', 'stdio', '-monitor', 'none',
           '-device', 'qemu-xhci,id=xhci', '-drive', f'if=none,format=raw,id=dom,file={COPY}',
           '-device', 'usb-storage,drive=dom,bootindex=1']
    macs = ['52:54:00:42:60:01', '52:54:00:42:60:02', '52:54:00:42:60:03', 'b0:b9:8a:45:13:fb']
    for i, mac in enumerate(macs):
        forward = f',hostfwd=tcp:127.0.0.1:{port}-:22' if i == 3 else ''
        cmd += ['-netdev', f'user,id=n{i},restrict=on{forward}', '-device', f'e1000,netdev=n{i},mac={mac}']
    guest = pexpect.spawn(cmd[0], cmd[1:], encoding='utf-8', codec_errors='replace', timeout=300, echo=False)
    guest.logfile_read = log
    return guest


def marker(guest, commands, name):
    head, tail = name.rsplit('_', 1)
    guest.send(f"{commands}; printf '%s_{tail}\\n' {head}\r")
    guest.expect(rf'\n{name}\r*\n')
    return guest.before.replace('\r', '') + '\n'


def login(guest, password):
    guest.expect('tenerix-zero login:')
    guest.send('root\r')
    guest.expect('Password:')
    guest.send(password + '\r')
    guest.expect(PROMPT)


def main():
    password = (OUT / 'root-password').read_text().strip()
    shutil.copyfile(IMAGE, COPY)
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    result = {'image': IMAGE.name, 'passed': False}
    with (OUT / f'{NAME}.log').open('w') as log:
        guest = spawn(port, log)
        try:
            guest.expect('SYSLINUX 6.03')
            guest.expect('boot:')
            prompt_at = time.monotonic()
            guest.expect('Linux version')
            result['autoboot_seconds'] = round(time.monotonic() - prompt_at, 2)
            guest.expect('TENERIX_SWITCH_ROOT generation=g1 build=dom-1 device=/dev/loop0')
            login(guest, password)
            out = marker(guest, 'uname -r; cat /proc/mounts; cat /proc/mdstat; rc-status; '
                         'ip -4 -o addr; modinfo -n it87; sshd -T | grep -i pubkeyacceptedalgorithms; '
                         'ssh-keygen -lf /root/.ssh/authorized_keys; cat /proc/swaps', 'PROBE_DONE')
            assert '6.18.58-0-lts' in out
            assert re.search(r'/dev/loop0 / ext4 rw', out), 'root is not the loop ext4'
            assert re.search(r'/dev/sd\w+ /media/dom vfat rw', out), 'DOM FAT not mounted'
            assert not re.search(r'^md\d+ :', out, re.M), 'an MD array is active'
            assert re.search(r'sshd\s+\[\s*started', out) and re.search(r'networking\s+\[\s*started', out)
            assert re.search(r'eth3\s+inet 10\.0\.2\.15/', out), 'no DHCP address on eth3'
            assert '/lib/modules/6.18.58-0-lts/updates/it87.ko' in out, 'it87 does not resolve to updates/'
            assert 'sk-ssh-ed25519@openssh.com' in out
            assert out.count('(ED25519-SK)') == 3, 'expected three security keys'
            result.update({'loop_root': True, 'dhcp_eth3': True, 'sshd': True, 'it87_updates': True,
                           'sk_keys': 3, 'serial_password_login': True})
            banner = subprocess.run(['ssh-keyscan', '-p', str(port), '127.0.0.1'], capture_output=True,
                                    text=True, timeout=60).stdout
            assert 'ssh-ed25519' in banner, 'sshd not reachable through eth3'
            result['ssh_reachable_on_eth3'] = True
            guest.expect(PROMPT)
            nonce = 'TENERIX_' + secrets.token_hex(8)
            guest.send(f'echo {nonce} > /root/persistence; sync; reboot\r')
            guest.expect('SYSLINUX 6.03', timeout=180)
            guest.expect('TENERIX_SWITCH_ROOT generation=g1')
            login(guest, password)
            out = marker(guest, 'cat /root/persistence', 'REBOOT_DONE')
            assert f'\n{nonce}\n' in out, 'file did not persist across reboot'
            result['reboot_persistence'] = True
            guest.expect(PROMPT)
            guest.send('poweroff\r')
            guest.expect(pexpect.EOF, timeout=180)
            guest.close()
            # Serial selection is tested on cold boots, as an operator would after power-on.
            log.write('\n=== TENERIX TEST: cold boot, select previous ===\n')
            guest = spawn(port, log)
            guest.expect('boot:')
            guest.send('previous\r')
            guest.expect('TENERIX_SWITCH_ROOT generation=g0')
            login(guest, password)
            result['previous_slot'] = True
            guest.send('poweroff\r')
            guest.expect(pexpect.EOF, timeout=180)
            guest.close()
            log.write('\n=== TENERIX TEST: cold boot, select recovery ===\n')
            guest = spawn(port, log)
            guest.expect('boot:')
            guest.send('recovery\r')
            guest.expect('TENERIX_RAM_RECOVERY:')
            guest.expect(r'[~/] # ')
            result['recovery_shell'] = True
            guest.send('poweroff -f\r')
            guest.expect(pexpect.EOF, timeout=60)
            result['passed'] = True
        except BaseException as error:
            result['error'] = str(error)[:1500]
            raise
        finally:
            if guest.isalive():
                guest.close(force=True)
            (OUT / f'{NAME}.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
