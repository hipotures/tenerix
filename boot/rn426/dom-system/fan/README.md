# RN426 fan control code map

The control policy is implemented in [`tenerix-fan`](tenerix-fan), installed as
`/usr/local/sbin/tenerix-fan` by [`../build.py`](../build.py).
This is a source-code identification; it does not verify the running device.

- `find_hwmon()` locates the `it8613` and `coretemp` sensor devices.
- `set_pwm()` writes `1` to `pwm2_enable` (manual mode) and the requested duty
  value to `pwm2` under the IT8613E hwmon device.
- The main loop reads CPU temperatures, board `temp2_input`, and `fan2_input`.
  By default it runs every five seconds. Every twelve loops it reads SATA disk
  temperatures from SMART attribute 194, skipping disks in standby.
- Normal duty is `80` on the `0–255` PWM scale. This is a duty setting, not an
  RPM target. CPU at least 70 C, board at least 50 C, or disk at least 55 C
  triggers duty `255`. Invalid CPU or board temperatures also trigger it.
- Normal duty resumes only when CPU is below 60 C, board below 45 C, and the
  hottest reported disk below 50 C. Missing disk temperatures do not trigger
  emergency mode.
- The TERM, INT, and HUP handlers attempt to set duty `255`. This does not
  cover SIGKILL, power loss, every script error, or failed sysfs writes.
  If sensor discovery fails at startup, the script exits without changing PWM.

[`tenerix-fan.conf`](tenerix-fan.conf), installed at `/etc/conf.d/tenerix-fan`,
sets the normal duty and temperature thresholds.
[`tenerix-fan.start`](tenerix-fan.start) starts the process through OpenRC's
`local` service; [`tenerix-fan.stop`](tenerix-fan.stop) requests its termination.
[`temps`](temps) displays `/run/tenerix-fan` and current sensor attributes; it
does not change fan speed.

The hardware interface is provided by the `it87` kernel module with IT8613E
support; see [`hardware/it8613e`](../../../../hardware/it8613e/README.md).
That driver exposes PWM and sensor attributes; the shell script above chooses
the operating duty and emergency thresholds.

## Manual descending PWM experiment

[`fan-descent.py`](fan-descent.py) is a separate Python 3 script, run manually
on the NAS. It requires root, smartctl, existing manual PWM mode, valid CPU,
board and SATA disk temperatures, and one running original fan keeper.

```sh
ssh -t tenerix 'cd /tmp/tenerix-fan-descent && python3 fan-descent.py'
```

At current PWM80, it starts immediately with PWM72, then tests **64, 56, 48,
40, 32, 24, 16, 8**, each for **ten minutes**. There is no extra PWM80 dwell.
It does not test PWM0 by default. Timestamped JSONL logs are created in the
working directory, and readings are printed to the terminal. `temps` and the
login status display show `mode=test` during sampling.

The original keeper is paused with SIGSTOP, preserving its process and policy.
It is not terminated: TERM would invoke its PWM255 handler. The test verifies
that the keeper is stopped before lowering PWM. On completion, Ctrl+C, TERM,
HUP or a detected error after takeover, the script attempts to restore the
initial PWM and resume the original keeper with SIGCONT. The experiment does
not request PWM255. The resumed keeper retains its own emergency policy.

Fast sensors are sampled every five seconds, SATA SMART temperatures every
minute. SMART calls have five-second timeouts and do not wake sleeping disks.
Missing readings, standby disks, invalid sensors, competing control writes or
RPM below 300 / above 10000 abort the experiment. The highest CPU sensor is
used, including package and core readings. Temperature stop limits are:

| Sensor | Absolute stop | Rise from initial sample |
| --- | --- | --- |
| CPU | 60 C | 10 C |
| Board | 45 C | 7 C |
| Each SATA disk | 48 C | 3 C |

These are conservative experimental guards, not manufacturer limits or a
measured safe minimum. A successful ten-minute stage does not establish thermal
equilibrium, operation under full load, or reliable fan restart. All aborts
return control to the existing keeper rather than introducing a new permanent
policy. SIGKILL, power loss, hung processes or failed hardware writes cannot be
recovered by Python's cleanup handler; run attended with independent access to
restore cooling. Do not stop or restart the original keeper during the test.

Local simulation tests:

```sh
python3 -m unittest discover -s boot/rn426/dom-system/fan -p 'test_*.py' -v
```

The corrected script has not been run on the hardware. The earlier aborted
experiment and restoration are recorded in
[`test-incident-2026-11-05.md`](test-incident-2026-11-05.md).
