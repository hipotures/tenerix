#!/usr/bin/env python3
"""Read-only, bounded monitoring after a separately authorized IT8613E load.

No register/sysfs writes, module operations, device probes or recovery actions.
"""
import json
from pathlib import Path
import time


def named_hwmon(name):
    matches = [p for p in Path('/sys/class/hwmon').glob('hwmon*')
               if (p / 'name').read_text().strip() == name]
    if len(matches) != 1:
        raise SystemExit(f'Expected exactly one {name} hwmon device')
    return matches[0]


def main():
    cpu = named_hwmon('coretemp')
    board = named_hwmon('it8613')
    start = time.monotonic()
    for index in range(13):
        sample = {'elapsed': round(time.monotonic() - start, 2)}
        for name, root in [('cpu', cpu), ('board', board)]:
            files = sorted(root.glob('temp*_input'))
            if name == 'board':
                files += sorted(root.glob('fan*_input'))
                files += [root / 'pwm2', root / 'pwm2_enable']
            sample[name] = {p.name: int(p.read_text()) for p in files}
        print(json.dumps(sample), flush=True)
        temps = sample['cpu'].values()
        if not temps or not all(0 < t < 75000 for t in temps):
            raise SystemExit('ABORT: CPU temperature invalid or >=75 C; notify operator')
        if not 0 < sample['board'].get('temp2_input', -1) < 70000:
            raise SystemExit('ABORT: reference board sensor invalid or >=70 C; notify operator')
        if sample['board'].get('fan2_input', 0) < 500:
            raise SystemExit('ABORT: fan2 below 500 RPM; notify operator; unloading is not recovery')
        if index < 12:
            time.sleep(5)
    print('MONITORING_COMPLETED: 60 seconds; no control writes', flush=True)


if __name__ == '__main__':
    main()
