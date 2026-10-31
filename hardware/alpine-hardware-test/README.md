# RN426 Alpine hardware test

Date: 2026-10-31. **Actual hardware:** NETGEAR RN426 / Atom C3538,
Alpine **3.24.3 Live**, kernel **6.18.58-0-lts**, Legacy BIOS.

**Results:** custom OLED text was displayed and visually confirmed by the
operator; all five physical buttons generated events. Our exact-ABI IT8613E
backport loaded successfully and reported valid board temperature and fan RPM.
A subsequent operator-authorized PWM test used 30 seconds per step; results are
recorded below and in `evidence/fan-test.log`. These are Alpine hardware results,
not transferred Debian measurements.

## Authorization and safety boundary

The final hardware-test request authorized ephemeral runtime dependencies,
i2c-dev/coretemp/hwmon-vid prerequisites and supervised insertion of the reviewed
module. Before insertion the operator confirmed physical attendance, normal
fan operation, UART and ability to supply emergency external airflow.

The first test made **no PWM writes**. The operator then explicitly requested
fan-speed changes and **30 seconds per change**, superseding the earlier PWM
prohibition for that bounded experiment only. The operator also reported an
older 300-second PWM-80 trial with stable temperature; that is historical
operator evidence, not a measured Alpine result of this task.

No production HDD/block-device contents, MD arrays, LUKS, Btrfs, encryption keys
or factory DOM were queried, mounted, assembled, unlocked or changed. No
partition, boot, firmware, network or SSH-authentication configuration changed.
No reboot, permanent installation, service registration or autoload occurred.
All NAS files created by this task are in ephemeral tmpfs, including package
state and `/tmp/tenerix-alpine-hw`. Development/compilation happened locally.

## Live prerequisites and reviewed package installation

Initial passive checks established:

```text
uname -r: 6.18.58-0-lts
/etc/alpine-release: 3.24.3
stat -f -c %T /: tmpfs
root: approximately 1.9 GiB available
MemAvailable: approximately 3540 MiB; Swap 0
it87 absent; no panel controller process; fuser /dev/mem exit 1
coretemp and i2c_dev available as exact-ABI in-tree modules, initially unloaded
```

Only `/media/sdh/apks` was configured locally, so the first simulation could not
resolve Python dependencies. Explicit official **v3.24/main and community** URLs
were passed per command; repository configuration was not edited. Reviewed:

```sh
apk add --simulate --no-cache \
  --repository https://dl-cdn.alpinelinux.org/alpine/v3.24/main \
  --repository https://dl-cdn.alpinelinux.org/alpine/v3.24/community \
  python3=3.14.10-r1 py3-pillow=12.2.0-r0 font-dejavu=2.37-r6 psmisc=23.7-r0
```

Simulation proposed **42 new packages, no upgrades/removals**, final **76.3 MiB
in 81 packages**. A local recursive fetch allowed maintainer-hook inspection
before the matching actual installation. New selected hooks were fontconfig
font-cache and mkfontscale directory regeneration; the existing BusyBox trigger
updates applet links. No module directory, kernel image, initramfs, bootloader,
network/service or storage hook was selected. Actual installation ran those
three triggers only. Full package output is in `evidence/runtime-install.log`.
No `apk upgrade`, build tools or kernel development packages were installed on
the NAS.

BusyBox modprobe does **not** implement `-n`; the attempted dry run failed
without loading anything. Its supported `-D` printed the required paths.
Then authorized `modprobe coretemp` and `modprobe i2c_dev` were executed.
Independent coretemp readings were **33–37°C** initially. I801 was already bound;
i2c-dev exposed its named **i2c-1** adapter. There was no I2C scan or forced access.

## OLED and button evidence

The minimal adapter changes are in [panel.py](../front-panel/panel.py):
OpenRC-aware fail-closed service checking, the same exclusive flock and mandatory
fuser check, and native Alpine/ Debian DejaVu font paths. Unknown init/service
status is refused. The read-only GPIO preflight now also acquires ownership.
No TrueNAS app code, daemon or installer is used. Upstream remains pinned at
**2968ee0514908d44b076ed1120f385a338bf1cd2**, with existing MIT attribution and
runtime SHA checks.

The existing narrow six-pad write boundary is unchanged: EN/RST cannot go low,
pad configuration cannot change, IRQ is read-only. MSP430 is read only at
register **0x04**, once per armed IRQ assertion after stable idle; register
**0x02 is never written**. No reset, alternate GPIO path or `iomem=relaxed` was
used. Existing `CONFIG_IO_STRICT_DEVMEM=y` permitted the reviewed mmap on this
actual system; successful access here does not license weakening future kernels.

Commands in the temporary panel directory:

```sh
python3 -m unittest -v test_panel
python3 panel.py preflight
python3 panel.py show 'Alpine 3.24' 'Tenerix OK'
python3 panel.py buttons --seconds 300 --echo
```

Thirteen adapter tests passed on the development host, Alpine builder and NAS.
GPIO preflight passed before and after testing:

```text
PADBAR N/S: 0x00000400
EN/RST: 0x05000201
IRQ: 0x45000102
READ-ONLY PREFLIGHT PASSED; no GPIO writes
frame sent: 210.74 ms
```

The operator visually confirmed both requested text lines, then confirmed arrow
operation. All five were also measured directly:

| Button | Bitmap | Events |
|---|---:|---:|
| UP | 4 | 1 |
| DOWN | 8 | 1 |
| LEFT | 1 | 2 |
| RIGHT | 2 | 1 |
| CENTER | 16 | 4 |

**Nine events / nine MCU reads.** Extra center/left presses were genuine observed
events; no claim is made about unobserved missed presses. The bounded listener
was stopped early using SIGTERM only after checking its exact PID command and
working directory. It printed final counts and released resources. No process
remained controlling `/dev/mem` (`fuser` exit 1). The final requested OLED text
was restored successfully, frame time **209.29 ms**. No physical mapping or
reset recovery was needed.

## IT8613E build and actual load

[Reproducible build instructions](../it8613e/alpine/README.md),
[exact compatibility manifest](../it8613e/alpine/compatibility.json),
[build evidence](evidence/module-build.log) and
[static validation](evidence/module-validation.log).

The retained signed Alpine **6.18.58-r0** dev/kernel package pair was found and
verified, so no 6.18.59 substitution or kernel upgrade was necessary. Generated
headers/config, exact `Module.symvers`, GCC **15.2.0-r5** and binutils **2.45.1-r1**
were used in a local Alpine container. Existing three-commit backport reused
unchanged; no speculative driver or API shim. The stock signed-package module
hash matches the running Live stock file exactly.

```text
module: it87.ko, 945688 bytes, GPL, x86-64 relocatable ELF
SHA-256: 1155aae1cb9e794f41a719dc34ffe8df4a950c0911bc3b9d97cc4d5990235cf9
vermagic: 6.18.58-0-lts SMP preempt mod_unload modversions
imports resolved: 42; matching version CRCs: 43, including module_layout
depends: hwmon,hwmon-vid
```

Three seeded builds under independent output paths, including a fresh offline
container, were byte-identical. Unseeded GCC latent-entropy instrumentation had
initially prevented reproducibility; supported fixed `-frandom-seed` resolves
this without dropping instrumentation. Stock kbuild skips BTF because the dev
package lacks vmlinux; this was documented rather than suppressed.

Insertion occurred only after operator cooling/recovery confirmation, exact
checksum/vermagic comparison, normal independent CPU temperature, no loaded
it87 and no fan-control daemon:

```sh
modprobe hwmon_vid
insmod /tmp/tenerix-alpine-hw/it87.ko \
  fix_pwm_polarity=0 update_vbat=0 ignore_resource_conflict=0
```

No force-ID, resource bypass or polarity correction was used. Result:

```text
INSERTION_SUCCEEDED
it87: loading out-of-tree module taints kernel.
it87: module verification failed: signature and/or required key missing - tainting kernel
it87: Found IT8613E chip at 0xa30, revision 3
it87: Beeping is supported
hwmon name: it8613
```

Unsigned-module/out-of-tree taint is expected; Legacy BIOS and lockdown-none
permitted loading. It is not evidence of a signature-enforcement bypass.
No new chip/resource warning appeared in the captured insertion lines.

The read-only [monitor.py](monitor.py) discovers hwmon by name and sampled 13
times over **60.07 seconds**:

| Measurement | Observed range/state |
|---|---|
| coretemp CPU readings | 30–35°C |
| IT8613 temp2 | 30°C |
| Fan2 | 2008–2020 RPM |
| PWM2 | 128 throughout |
| PWM2 enable | 1, manual, throughout |
| temp1/temp3 | -128°C, invalid/unconnected; **not usable temperature sensors** |
| Fan3 | 0; no connected working fan inferred |

The operator confirmed no noticeable fan change or other problem. Initial
acoustic “full speed” was an operator description: **PWM 128 is not full-scale
255**. Pre-load tach/PWM values were unavailable, so no claim is made that
insertion preserved every pre-existing register. The driver can write monitoring,
limit and tach configuration merely by loading; see the original source risk
review. Unloading is not assumed to restore hardware state.

## Separately authorized fan-speed test

The operator requested 30 seconds at every changed speed. [fan-test.py](fan-test.py)
uses the same named hwmon devices and exact staged-module checksum. Preconditions:
manual mode 1, baseline PWM128, no competing fan daemon and normal independent
CPU/board temperature and tach. Only **pwm2** is written, at 112 → 96 → 80 → 128;
mode, frequency, alarm limits and GPIO remain unchanged. The prepared script
was streamed over SSH to Python in the tmpfs test directory, using the reviewed
read-only monitor helper; no shell writes to other hardware occurred.

Every step has seven readings at 5-second intervals over 30 seconds. Normal
completion restores and verifies 128. Exceptions, SIGINT/SIGTERM/SIGHUP,
readback mismatch, CPU ≥65°C, board ≥45°C, invalid temperatures or RPM outside
800–8000 trigger full-scale **255** in `finally`. This is a bounded supervised
experiment, not a control policy or unattended safety certification. Sudden
power loss/SIGKILL cannot execute software cleanup. External cooling remains
the operator recovery; neither unloading nor reboot is presumed to recover.
Three software tests verify normal restoration, short PWM80-only restoration and temperature-abort full speed
with fake device files. No production storage is touched by the script.

Actual run completed **120.02 seconds**, without an abort. Fan RPM ranges below
use the last approximately ten seconds of each 30-second step, allowing spin
transition to settle; raw samples include transitions too.

| PWM2 | Duration | Settled Fan2 RPM |
|---:|---:|---:|
| 112 | 30 s | 1854–1854 |
| 96 | 30 s | 1700–1700 |
| 80 | 30 s | 1537–1541 |
| 128 | 30 s | 2008–2014 |

CPU readings stayed **30–35°C**, board temp2 **29–30°C**. Mode remained **1**.
Final record: `{"restored_pwm2": 128, "emergency": false}`. Thus actual speed
control is verified on Alpine at these three tested reductions, with baseline
restored. The test does not establish safe cooling under disk/CPU load or justify
setting PWM80 permanently. No full-speed emergency write was required.

Evidence: [fan-test.log](evidence/fan-test.log).

Repeat PWM80-only test: **30.00 seconds**,
settled Fan2 **1534–1537 RPM**,
board **30–30°C**, CPU **29–35°C**.
The operator confirmed “it works.” Final PWM128 restoration succeeded without
an emergency. Evidence: [fan-test-80-repeat.log](evidence/fan-test-80-repeat.log).


## Runtime/deployment readiness

[runtime-packages.txt](runtime-packages.txt) pins the requested direct packages;
[runtime-resolved.txt](runtime-resolved.txt) records the actual local resolved
closure. It includes OpenRC/SSH, mdadm/cryptsetup/Btrfs, NFS/OpenRC/rpcbind,
Python/Pillow/fonts, SMART and Intel microcode. Custom module and panel source
are provided by the version-pinned deployment bundle, with no service hooks.

A **local isolated root**, with package scripts disabled, installed that set plus
the exact signed linux-lts-6.18.58-r0 package: **120 packages, 252.9 MiB according
to APK; 277288 KiB (270.79 MiB) allocated by du**. Boot files were 36668 KiB,
compressed module tree 145912 KiB. This is a measured package footprint, not an
installed/bootable NAS image; initramfs generation, custom files, runtime state,
logs, caches and update staging still need headroom. Allow 0.5–1 GiB for a
maintainable root with two module generations and ample free update space.
Four-GiB root storage is practical. No NFS/storage/SSH service from this model
was started on the NAS. The mdadm/initramfs auto-assembly hazards from the
Alpine audit remain unresolved for deployment; never install this manifest
blindly on the production-connected Live session.

**Kernel coupling:** this module is only for **6.18.58-0-lts**, matching hwmon and
hwmon-vid. Neither 6.18.59 nor Debian may use it. Pair future kernel/initramfs,
module tree and rebuilt external driver as one reviewed boot generation. Keep a
working prior generation and serial recovery; no automatic boot modification is
provided. Panel is userspace but still requires matching tested hardware, fonts,
i801/i2c-dev and permitted /dev/mem access. No OpenRC daemon is enabled here.

## Retained local artifacts

All paths are relative to the repository; generated outputs are Git-ignored:

- `artifacts/alpine-hardware/repro-one/it87.ko` — hardware-tested module above.
- `artifacts/alpine-hardware/repro-two/it87.ko` and `offline-rebuild/it87.ko` — identical reproductions.
- `artifacts/alpine-hardware/packages/` — authenticated old kernel/dev pair.
- `artifacts/alpine-hardware/builder-apks/` — exact authenticated build/test closure.
- `artifacts/alpine-hardware/tenerix-rn426-6.18.58-0-lts.tar.gz` and `.sha256` — deployment bundle, **267214 bytes**, SHA-256 **`2dd8b56d1ee560eebf5bdf95dbac6df70efc9b37decea18970cd13c0dd618bfb`**.
- NAS `/tmp/tenerix-alpine-hw/it87.ko` — same checksum; ephemeral.

Source/provenance/licenses/scripts and sanitized evidence are committed; binaries,
raw private log material and package archives are not. No credentials or private
hardware identifiers are included.

## Final state, limitations and next test

Final PWM readback is **128**, mode **1**. The module remains loaded intentionally: unloading is not rollback. Stock module
files remain unchanged; no depmod, autoload or initramfs installation occurred.
The panel listener is stopped and resources released; OLED retains requested
text. Runtime packages and temporary artifacts disappear on reboot. The module
has actual Alpine detection/RPM/temperature evidence; accurate temperature
calibration, all tach channels, load thermal behavior and unattended failure
handling are not certified. No automatic fan service or permanent minimum PWM
is selected by this experiment.

The operator also requested and confirmed a second short PWM80-only run; its
measured record is included below. To repeat only that bounded variant after
separate authorization, use `python3 fan-test.py --pwm80-only` on the prepared
target. It holds PWM80 for 30 seconds and restores128, rather than rerunning
all four steps.

Next requires explicit authorization: longer monitored thermal qualification
using a defined workload and conservative fail-safe curve, followed by a separate
review of service ownership/startup/update/recovery integration. No automatic
production-storage activation, NFS rollout or operating-system installation is
included.


## Command record

Target commands were executed over the existing authorized SSH password session
with normal host-key verification; credentials were never saved in source or
logs. These were the actual classes of operations:

| Stage | Commands / effects |
|---|---|
| Baseline | `uname`, release read, `stat -f`, `free`, `df`, `/proc/modules`, mount inventory, `rc-status`, process names, module metadata and named hwmon reads |
| Dependencies | Pinned `apk add --simulate`, local archive hook review, then the matching four direct runtime requests; only Live RAM changed |
| Prerequisites | `modprobe -D`, then `modprobe coretemp`, `modprobe i2c_dev`; no bus scan |
| Panel | Guarded tmpfs transfer, unittest, `preflight`, `show`, bounded interrupt-only `buttons`; verified task-owned SIGTERM |
| Driver | Checksum/vermagic comparison, `modprobe hwmon_vid`, absolute-path `insmod` shown above, filtered `dmesg` |
| Initial observation | `python3 -` streaming `monitor.py`; 60 seconds of sysfs reads |
| Later fan authorization | `python3 -` streaming `fan-test.py`; only named `it8613/pwm2` writes, four 30-second steps, original 128 restored |
| Post-check | Named sensor/PWM reads, filtered kernel diagnostics, `fuser -s /dev/mem` |
| Development only | Signed package fetch/verify, container compilation/rebuild, modinfo/readelf/nm/CRC inspection, fake-device tests, isolated runtime-size measurement and deterministic bundle creation |

No hardware-control process remains running after these bounded tests. The loaded
module continues its normal kernel monitoring role. The initial and post-load
panel register snapshots match. Final post-fan readback and kernel lines are in
[evidence/post-fan.log](evidence/post-fan.log); no BUG/Oops/lockup appeared in
that filtered check. This is not a comprehensive long-duration reliability test.
