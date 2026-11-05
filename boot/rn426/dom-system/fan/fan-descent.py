#!/usr/bin/env python3
"""Supervised RN426 PWM descent: ten minutes per step, original PWM restored."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


class Abort(RuntimeError):
    pass


def interrupted(signum, _frame):
    raise Abort(f'Interrupted by signal {signum}')


def hwmon(name):
    matches = [p for p in Path('/sys/class/hwmon').glob('hwmon*')
               if (p / 'name').read_text().strip() == name]
    if len(matches) != 1:
        raise Abort(f'Expected exactly one {name} hwmon device')
    return matches[0]


def temperature(value):
    if type(value) is not int or not 0 < value < 120:
        raise Abort(f'Invalid temperature: {value!r}')
    return value


def stages(initial, step, minimum):
    if not 0 <= minimum < initial <= 255 or step <= 0:
        raise Abort('Require 0 <= minimum < current PWM <= 255 and positive step')
    value = initial
    while value > minimum:
        value = max(minimum, value - step)
        yield value


class Hardware:
    def __init__(self):
        self.board = hwmon('it8613')
        self.cpu = hwmon('coretemp')
        self.disks = [p for p in Path('/sys/block').glob('sd*')
                      if (p / 'removable').read_text().strip() == '0'
                      and any(part.startswith('ata') and part[3:].isdigit()
                              for part in (p / 'device').resolve().parts)]
        if not self.disks:
            raise Abort('No internal SATA disks found; disk temperatures required')
        self.disk_values = {}
        self.disk_at = None

    def pwm(self):
        return int((self.board / 'pwm2').read_text())

    def manual(self):
        if (self.board / 'pwm2_enable').read_text().strip() != '1':
            raise Abort('Expected existing manual PWM mode 1')

    def set_pwm(self, value):
        self.manual()
        (self.board / 'pwm2').write_text(f'{value}\n')
        if self.pwm() != value:
            raise Abort('PWM write readback mismatch')

    def restore(self, value):
        (self.board / 'pwm2_enable').write_text('1\n')
        (self.board / 'pwm2').write_text(f'{value}\n')
        if self.pwm() != value:
            raise Abort('Original PWM restoration readback failed')

    def sample(self, expected):
        self.manual()
        if self.pwm() != expected:
            raise Abort('PWM changed unexpectedly: possible competing controller')
        values = [int(p.read_text()) / 1000 for p in self.cpu.glob('temp*_input')]
        if not values or any(not 0 < value < 120 for value in values):
            raise Abort('Missing or invalid CPU temperature')
        board = int((self.board / 'temp2_input').read_text()) / 1000
        if not 0 < board < 120:
            raise Abort('Invalid board temperature')
        rpm = int((self.board / 'fan2_input').read_text())
        # Experimental abort limits, not manufacturer operating specifications.
        if max(values) >= 60 or board >= 45 or not 300 <= rpm <= 10000:
            raise Abort(f'CPU/board/RPM test limit: {max(values)}C / {board}C / {rpm}rpm')
        now = time.monotonic()
        if self.disk_at is None or now - self.disk_at >= 60:
            updated = {}
            for disk in self.disks:
                result = subprocess.run(
                    ['smartctl', '-n', 'standby', '-A', '-j', f'/dev/{disk.name}'],
                    capture_output=True, text=True, timeout=5, check=False)
                # Bits 0-2 denote command/device/SMART command errors. Standby
                # skips also refuse the test: never wake a disk or guess its temperature.
                if result.returncode < 0 or result.returncode & 7:
                    raise Abort(f'{disk.name}: SMART unavailable or disk in standby')
                data = json.loads(result.stdout)
                updated[disk.name] = temperature(data.get('temperature', {}).get('current'))
            self.disk_values = updated
            self.disk_at = time.monotonic()
            # Recheck fast sensors after potentially slow SMART commands.
            return self.sample(expected)
        return {'cpu_c': max(values), 'board_c': board, 'rpm': rpm,
                'disks_c': dict(self.disk_values), 'pwm': expected,
                'disk_age_s': round(now - self.disk_at, 1)}


def check_limits(sample, baseline):
    if sample['cpu_c'] >= 60 or sample['cpu_c'] - baseline['cpu_c'] >= 10:
        raise Abort('CPU reached 60 C or rose by 10 C from baseline')
    if sample['board_c'] >= 45 or sample['board_c'] - baseline['board_c'] >= 7:
        raise Abort('Board reached 45 C or rose by 7 C from baseline')
    for disk, value in sample['disks_c'].items():
        if value >= 48 or value - baseline['disks_c'][disk] >= 3:
            raise Abort(f'{disk}: disk reached 48 C or rose by 3 C from baseline')


def keeper_processes():
    found = []
    for entry in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            args = entry.read_bytes().split(b'\0')
        except (FileNotFoundError, ProcessLookupError):
            continue
        if b'/usr/local/sbin/tenerix-fan' in args:
            found.append(int(entry.parent.name))
        if any(Path(os.fsdecode(arg)).name in ('fancontrol', 'pwmconfig') for arg in args if arg):
            raise Abort('Another fan controller is running')
    return found


def paused(pid):
    for line in Path(f'/proc/{pid}/status').read_text().splitlines():
        if line.startswith('State:'):
            return line.split()[1] in ('T', 't')
    raise Abort('Cannot read keeper process state')


def pause_keepers(pids):
    # TERM would invoke the existing keeper's PWM255 handler. STOP cannot
    # invoke that handler; preserve the process and its policy for CONT.
    for pid in pids:
        os.kill(pid, signal.SIGSTOP)
    deadline = time.monotonic() + 2
    while not all(paused(pid) for pid in pids):
        if time.monotonic() >= deadline:
            raise Abort('Could not pause the existing keeper')
        time.sleep(0.05)


def resume_keepers(pids):
    for pid in pids:
        if pid not in keeper_processes():
            raise Abort('Original keeper exited; cannot resume it')
        os.kill(pid, signal.SIGCONT)


def run_test(hw, emit, minimum=8, step=8, minutes=10):
    initial = hw.pwm()
    plan = list(stages(initial, step, minimum))
    baseline = hw.sample(initial)
    check_limits(baseline, baseline)
    keepers = keeper_processes()
    if len(keepers) != 1 or paused(keepers[0]):
        raise Abort('Require one running original keeper to resume after the test')
    emit({'event': 'baseline', **baseline, 'stages': plan, 'minutes_per_stage': minutes})
    try:
        pause_keepers(keepers)
        emit({'event': 'keeper_paused', 'count': len(keepers)})
        for value in plan:
            if keeper_processes() != keepers or not all(paused(pid) for pid in keepers):
                raise Abort('Keeper ownership changed during the test')
            hw.set_pwm(value)
            start = time.monotonic()
            emit({'event': 'stage_start', 'pwm': value})
            while True:
                sample = hw.sample(value)
                emit({'event': 'sample', 'stage_elapsed_s': round(time.monotonic() - start, 1), **sample})
                check_limits(sample, baseline)
                remaining = minutes * 60 - (time.monotonic() - start)
                if remaining <= 0:
                    break
                time.sleep(min(5, remaining))
            emit({'event': 'stage_complete', 'pwm': value})
        emit({'event': 'complete', 'message': 'Observed stages are not a qualified operating minimum'})
    finally:
        handlers = {sig: signal.signal(sig, signal.SIG_IGN)
                    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        try:
            try:
                hw.restore(initial)
            finally:
                resume_keepers(keepers)
            emit({'event': 'recovery', 'pwm': initial, 'keeper': 'resumed'})
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minimum', type=int, default=8,
                        help='Lowest PWM to test (default 8); 0 requires an explicit --minimum 0')
    parser.add_argument('--step', type=int, default=8)
    parser.add_argument('--minutes', type=int, default=10)
    parser.add_argument('--log', type=Path, default=Path(f'fan-descent-{time.strftime("%Y%m%d-%H%M%S")}.jsonl'))
    args = parser.parse_args()
    if args.minutes < 1 or args.step < 1 or not 0 <= args.minimum < 255:
        parser.error('Require positive minutes/step and minimum in 0..254')
    if os.geteuid() != 0:
        parser.error('Run as root on the RN426')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    with open('/run/tenerix-fan-descent.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Exclusive log creation avoids overwriting existing files as root.
        with args.log.open('x') as log:
            def emit(record):
                line = json.dumps({'time': time.strftime('%Y-%m-%dT%H:%M:%S%z'), **record})
                log.write(line + '\n')
                log.flush()
                if record['event'] == 'sample':
                    disks = list(record['disks_c'].values())
                    status = (f"cpu={record['cpu_c']:g}C board={record['board_c']:g}C "
                              f"hdd={min(disks)}-{max(disks)}C fan={record['rpm']}rpm "
                              f"pwm2={record['pwm']} mode=test at {time.strftime('%F %T')}\n")
                    temporary = Path('/run/tenerix-fan-descent.status')
                    temporary.write_text(status)
                    temporary.replace('/run/tenerix-fan')
                elif record['event'] == 'recovery':
                    Path('/run/tenerix-fan').unlink(missing_ok=True)
                # A lost SSH output stream must not prevent local logging/recovery.
                try:
                    print(line, flush=True)
                except (BrokenPipeError, OSError):
                    pass
            try:
                run_test(Hardware(), emit, args.minimum, args.step, args.minutes)
            except Exception as exc:
                emit({'event': 'abort', 'reason': str(exc)})
                return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
