#!/usr/bin/env python3
"""Isolated QEMU fixture creation and persistent BIOS/UART integration tests.

  qemu.py fixture                              create the disposable synthetic arrays
  qemu.py boot NAME [--dom IMG] [--select L]   boot a DOM image, log in over serial, probe
  qemu.py recovery NAME [--dom IMG]            select the RAM-only recovery entry
"""
import argparse
import json
from pathlib import Path
import re
import secrets
import socket
import subprocess
import time

import pexpect

from domlib import OUT, checked_image

BUILD = OUT / 'build'
PROMPT = r'tenerix-zero:[^\r\n]*# '
FAILURE = r'Initramfs unpacking failed[^\r\n]*|Kernel panic[^\r\n]*|TENERIX_RECOVERY:[^\r\n]*'


def images():
    files = [OUT / f'system-member-{i}.raw' for i in range(1, 7)]
    for p in files:
        if not p.is_file() or p.is_symlink() or p.stat().st_size != 4563402752:
            raise RuntimeError('Only regular synthetic image files with exact fixture size allowed')
    return files


def command(dom=None, fixture=False, port=None, degraded=False):
    cmd = ['qemu-system-x86_64', '-machine', 'pc,accel=tcg', '-cpu', 'max', '-smp', '2',
           '-m', '2048', '-display', 'none', '-serial', 'stdio', '-monitor', 'none']
    for i, p in enumerate(images()[:5] if degraded else images()):
        letter = 'abcdef'[i]
        cmd += ['-drive', f'if=none,format=raw,id=member{i},file={p}',
                '-device', f'virtio-blk-pci,drive=member{i},serial=TENERIX-FIXTURE-{letter}']
    if fixture:
        cmd += ['-kernel', str(BUILD / 'rootfs/boot/vmlinuz-lts'), '-initrd', str(BUILD / 'fixture-initramfs'),
                '-append', 'console=ttyS0,115200n8 panic=0', '-nic', 'none',
                '-virtfs', f'local,path={BUILD},mount_tag=input,security_model=none,readonly=on']
    else:
        dom = checked_image(dom)
        cmd += ['-device', 'qemu-xhci,id=xhci',
                '-drive', f'if=none,format=raw,readonly=on,id=dom,file={dom}',
                '-device', 'usb-storage,drive=dom,bootindex=1']
        # Four synthetic NICs; eth3 exercises DHCP and SSH, no external connectivity.
        for i in range(4):
            forwarding = f',hostfwd=tcp:127.0.0.1:{port}-:22' if i == 3 else ''
            cmd += ['-netdev', f'user,id=net{i},restrict=on{forwarding}',
                    '-device', f'e1000,netdev=net{i},mac=52:54:00:42:60:0{i + 1}']
    return cmd


def marker(guest, commands, name):
    """Run commands and return their output. The marker is joined by printf, so the echoed
    (and possibly line-wrapped) command line can never match it."""
    head, tail = name.rsplit('_', 1)
    guest.send(f"{commands}; printf '%s_{tail}\\n' {head}\r")
    guest.expect(rf'\n{name}\r*\n')
    # The match consumed the newline that ended the last output line; restore it.
    return guest.before.replace('\r', '') + '\n'


def login(guest):
    guest.expect('tenerix-zero login:', timeout=300)
    guest.send('root\r')
    guest.expect(PROMPT)


def boot_test(guest, args, port, result, started):
    if args.select:
        guest.expect('boot:')
        guest.send(args.select + '\r')
    else:
        guest.expect('boot:')
        prompt_at = time.monotonic()
        guest.expect('Linux version', timeout=300)
        result['autoboot_seconds_after_prompt'] = round(time.monotonic() - prompt_at, 2)
    guest.expect(rf'TENERIX_SWITCH_ROOT generation={args.slot} build={args.build} ', timeout=300)
    login(guest)
    result['seconds_to_login'] = round(time.monotonic() - started, 2)
    observed = marker(guest, 'uname -r; cat /run/tenerix-generation /run/tenerix-build; cat /proc/mdstat; '
                             'cat /proc/mounts; cat /proc/swaps; rc-status; ip -4 addr show eth3; netstat -lnt',
                      'PERSISTENT_PROBE_DONE')
    assert re.search(r'/dev/md0 / ext4 rw', observed), 'root is not persistent MD ext4'
    assert '6.18.58-0-lts' in observed
    assert f'\n{args.slot}\n{args.build}\n' in observed, 'slot/build marker mismatch'
    assert 'md1 :' not in observed and 'md2 :' not in observed, 'decoy array assembled'
    assert re.search(r'md0 : active raid1', observed)
    assert ('[6/5]' if args.degraded else '[6/6]') in observed
    assert '/dev/md' not in observed.split('Priority', 1)[1].split('Runlevel', 1)[0], 'swap active'
    assert re.search(r'inet 10\.0\.2\.', observed), 'DHCP not demonstrated'
    assert re.search(r'sshd\s+\[\s*started', observed), 'sshd did not start'
    result.update({'md_root_mounted': True, 'slot': args.slot, 'build': args.build, 'openrc': True,
                   'serial_login': True, 'dhcp': True, 'only_system_md': True, 'no_swap': True})
    ssh = ['ssh', '-i', str(OUT / 'test-admin'), '-o', 'IdentitiesOnly=yes',
           '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new',
           '-o', f'UserKnownHostsFile={OUT / "test-known-hosts"}', '-p', str(port), 'root@127.0.0.1',
           'echo SSH_PROTOTYPE_OK; cat /run/tenerix-build']
    check = subprocess.check_output(ssh, text=True, stderr=subprocess.STDOUT, timeout=60)
    assert 'SSH_PROTOTYPE_OK' in check and args.build in check
    result['ssh_key_login'] = True
    guest.expect(PROMPT)
    if args.reboot:
        nonce = 'TENERIX_PERSISTENCE_' + secrets.token_hex(8)
        guest.send(f"echo {nonce} > /root/persistence-test; sync; reboot\r")
        guest.expect('SYSLINUX 6.03', timeout=180)
        guest.expect(rf'TENERIX_SWITCH_ROOT generation={args.slot} ', timeout=300)
        login(guest)
        observed = marker(guest, 'cat /root/persistence-test', 'REBOOT_CHECK_DONE')
        assert re.search(rf'\n{nonce}\n', observed), 'persistence nonce missing'
        result.update({'persistence_nonce': nonce, 'clean_reboot_persistence': True})
        guest.expect(PROMPT)
    guest.send('poweroff\r')
    guest.expect(pexpect.EOF, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=['fixture', 'boot', 'recovery'])
    parser.add_argument('name', nargs='?', default='fixture', help='log and result file name')
    parser.add_argument('--dom', type=Path, default=OUT / 'tenerix-rn426-alpine-boot.img')
    parser.add_argument('--select', help='label typed at the SYSLINUX boot: prompt (default: timeout)')
    parser.add_argument('--slot', default='g1', help='expected tenerix.slot')
    parser.add_argument('--build', default='proto-b', help='expected initramfs BUILD_ID')
    parser.add_argument('--degraded', action='store_true', help='attach only five members')
    parser.add_argument('--reboot', action='store_true', help='verify persistence across a clean reboot')
    parser.add_argument('--fail-first', action='store_true',
                        help='let the default entry fail, power-cycle, then boot with --select')
    args = parser.parse_args()
    (OUT / 'logs').mkdir(exist_ok=True)
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    cmd = command(args.dom, args.mode == 'fixture', port, args.degraded)
    result = {'name': args.name, 'mode': args.mode, 'dom': args.dom.name, 'select': args.select,
              'acceleration': 'TCG', 'command': cmd, 'passed': False}
    started = time.monotonic()
    with (OUT / 'logs' / f'{args.name}.log').open('w') as log:
        if args.fail_first:
            guest = pexpect.spawn(cmd[0], cmd[1:], encoding='utf-8', codec_errors='replace', timeout=300, echo=False)
            guest.logfile_read = log
            try:
                guest.expect('boot:')
                guest.expect(FAILURE)
                result['first_boot_failure'] = guest.after.strip()
                # Hold briefly so the failure path settles, then cut power as an operator would.
                time.sleep(5)
            finally:
                guest.close(force=True)
            log.write('\n=== TENERIX TEST: power cycle after observed failure ===\n')
        guest = pexpect.spawn(cmd[0], cmd[1:], encoding='utf-8', codec_errors='replace', timeout=180, echo=False)
        guest.logfile_read = log
        try:
            if args.mode == 'fixture':
                (OUT / 'test-known-hosts').unlink(missing_ok=True)
                guest.expect('FIXTURE_CREATED_CLEAN', timeout=900)
                guest.expect(pexpect.EOF, timeout=60)
            else:
                guest.expect('SYSLINUX 6.03')
                result['factory_syslinux'] = True
                if args.mode == 'recovery':
                    guest.expect('boot:')
                    guest.send('recovery\r')
                    guest.expect('TENERIX_RAM_RECOVERY:', timeout=300)
                    guest.expect(r'[~/] # ')
                    observed = marker(guest, 'cat /proc/mdstat; cat /proc/mounts', 'RECOVERY_INPUT_OK')
                    assert 'md0' not in observed and '/dev/md' not in observed and '/dev/vd' not in observed
                    result['recovery_ram_shell'] = True
                    guest.send('poweroff -f\r')
                    guest.expect(pexpect.EOF, timeout=60)
                else:
                    boot_test(guest, args, port, result, started)
            guest.close()
            assert guest.exitstatus == 0, f'QEMU exit {guest.exitstatus}'
            result['passed'] = True
        except BaseException as error:
            result['error'] = str(error)[:2000]
            raise
        finally:
            if guest.isalive(): guest.close(force=True)
            result['elapsed_seconds'] = round(time.monotonic() - started, 2)
            (OUT / 'logs' / f'{args.name}.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps({k: v for k, v in result.items() if k != 'command'}, indent=2), flush=True)


if __name__ == '__main__':
    main()
