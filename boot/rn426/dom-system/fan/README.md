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
