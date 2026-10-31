#!/usr/bin/env python3
"""Operator-authorized RN426 fan test: 30 s per step, baseline restored.

Writes only it8613/pwm2; never changes mode, thresholds, GPIO or storage.
Requires physical supervision and external cooling recovery. Not a daemon.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import signal
import time

from monitor import named_hwmon

MODULE_SHA = '1155aae1cb9e794f41a719dc34ffe8df4a950c0911bc3b9d97cc4d5990235cf9'


def interrupted(signum, frame):
    raise RuntimeError(f'Test interrupted by signal {signum}')


def main(pwm80_only=False):
    if Path('/proc/sys/kernel/osrelease').read_text().strip() != '6.18.58-0-lts':
        raise RuntimeError('Exact tested Alpine kernel required')
    module = Path('/tmp/tenerix-alpine-hw/it87.ko')
    if hashlib.sha256(module.read_bytes()).hexdigest() != MODULE_SHA:
        raise RuntimeError('Unexpected staged module checksum')
    cpu, board = named_hwmon('coretemp'), named_hwmon('it8613')
    pwm, mode = board / 'pwm2', board / 'pwm2_enable'
    with open('/run/lock/rn426-fan-test.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if int(mode.read_text()) != 1 or int(pwm.read_text()) != 128:
            raise RuntimeError('Expected existing manual mode 1 / PWM 128; refusing mode changes')
        for comm in Path('/proc').glob('[0-9]*/comm'):
            try:
                name = comm.read_text().strip()
            except FileNotFoundError:
                continue
            if name in ('fancontrol', 'pwmconfig'):
                raise RuntimeError(f'Conflicting controller: {name}')
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, interrupted)
        start = time.monotonic()

        def sample(stage):
            cpu_values = {p.name: int(p.read_text()) for p in cpu.glob('temp*_input')}
            result = {'elapsed': round(time.monotonic() - start, 2), 'stage': stage,
                      'cpu': cpu_values, 'temp2_input': int((board / 'temp2_input').read_text()),
                      'fan2_input': int((board / 'fan2_input').read_text()),
                      'pwm2': int(pwm.read_text()), 'pwm2_enable': int(mode.read_text())}
            print(json.dumps(result), flush=True)
            if not cpu_values or not all(0 < t < 65000 for t in cpu_values.values()):
                raise RuntimeError('CPU temperature invalid or >=65 C')
            if not 0 < result['temp2_input'] < 45000:
                raise RuntimeError('Board temperature invalid or >=45 C')
            if not 800 <= result['fan2_input'] <= 8000:
                raise RuntimeError('Fan2 RPM outside supervised test limits')
            if result['pwm2_enable'] != 1 or result['pwm2'] != stage:
                raise RuntimeError('Unexpected controller state or another writer')

        def set_pwm(value):
            pwm.write_text(str(value) + '\n')
            if int(pwm.read_text()) != value:
                raise RuntimeError('PWM write did not read back correctly')

        sample(128)  # Validate independent temperatures and tach before any control write.
        failed = True
        try:
            for value in ((80,) if pwm80_only else (112, 96, 80, 128)):
                set_pwm(value)
                step_start = time.monotonic()
                for index in range(7):
                    deadline = step_start + index * 5
                    time.sleep(max(0, deadline - time.monotonic()))
                    sample(value)
            failed = False
        finally:
            # Fail full-speed on error/disconnect; never rely on unloading or reboot.
            recovery = 255 if failed else 128
            set_pwm(recovery)
            print(json.dumps({'restored_pwm2': recovery, 'emergency': failed}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pwm80-only', action='store_true',
                        help='30 seconds at PWM80, then restore baseline128')
    main(parser.parse_args().pwm80_only)
