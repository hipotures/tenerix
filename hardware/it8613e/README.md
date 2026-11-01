# RN426 IT8613E backport

**Alpine update:** exact `6.18.58-0-lts` build and successful monitoring-only hardware test are documented in [alpine/README.md](alpine/README.md) and the [Alpine hardware test](../alpine-hardware-test/README.md). The Debian record below remains historical. The shared validator now accepts explicit target/header/stock paths for file-only validation on a different build host; the Debian Makefile still requires its exact running ABI.

Date: 2026-10-31. Target: **6.12.107+deb13-amd64**, Debian kernel package **6.12.107-1**. Scope: source preparation, compilation and static validation only.

**Result:** a reproducible `it87.ko` compiled successfully on the RN426. Two builds under different paths were byte-identical. The module was **not installed or loaded**. Fan/PWM/Super I/O/GPIO/I2C registers were not accessed by the task. Production HDDs, MD arrays, LUKS and filesystems were not queried or changed. The stock module is unchanged.

**Load recommendation:** the binary passes static ABI checks, but a first load is **not approved as safe on the current production-connected chassis**. Initialization is not read-only. Resolve cooling recovery and firmware-ownership questions, then arrange an isolated supervised test before authorizing loading. Successful compilation does not validate temperature accuracy, tachometer scaling, pin mapping or cooling behavior.

Evidence labels used here: **VERIFIED** (actual build/inspection), **SOURCE FACT** (pinned source), **INFERRED**, **UNKNOWN**, **REQUIRES TEST**. Earlier evidence remains in the [factory audit](../../docs/audits/readynas-rn426-audit.md), [boot audit](../../docs/audits/readynas-rn426-boot-audit.md), and [Debian Live audit](../../docs/audits/readynas-rn426-debian13-audit.md).

## Files and reproducibility

| File | Purpose |
|---|---|
| `upstream/linux-6.12.107-it87.c` | Immutable stable baseline, unmodified |
| `upstream/*.patch` | Original accepted three-commit series, retained for review; not directly applied by Makefile |
| `upstream/linux-it8613e-upstream.c` | Exact accepted upstream reference implementation, unmodified |
| `patches/0001-backport-it8613e-linux-6.12.107.patch` | Consolidated adapted series applied to the stable baseline |
| `provenance.json` | Commit pins and source/module checksums |
| `SOURCES.sha256` | Hashes for source inputs and Kbuild |
| `Makefile`, `Kbuild` | Exact-ABI, unprivileged external-module build; no install/load targets |
| `validate.py` | File-only ELF, dependency, vermagic and exported-symbol CRC checks |
| `verify-source.py` | Offline zero-fuzz patch/hash check and equality to upstream with IT8689 omitted |
| `evidence/` | Actual build, reproduction, validation, package-hook and ownership records |
| `COPYING` | GPL-2.0 license from the stable baseline |
| `build/`, `artifacts/` | Generated output/local binary retention, excluded from Git |

Build prerequisites must already be present and reviewed. On the exact running kernel, in this directory:

```sh
make
python3 validate.py build/it87.ko
```

On the development machine, `python3 hardware/it8613e/verify-source.py` independently checks patch application and source equivalence without contacting hardware.

These commands compile/inspect only. They do not fetch/install packages, register DKMS, run depmod, install a module, rebuild an initramfs or load anything. The Makefile refuses a different running/header release and requires the exact headers' `Module.symvers`. It applies the patch with zero fuzz, uses kbuild, `W=1`, `-Werror`, two jobs and normalized source paths. It pins build user/host/time metadata. See [kernel external-module documentation](https://docs.kernel.org/kbuild/modules.html).

### Retained artifact

- NAS build: `/tmp/rn426-it8613e.EttJjj/build/it87.ko`.
- Independent NAS rebuild: `/tmp/rn426-it8613e.EttJjj/rebuild/build/it87.ko`.
- Local retained copy: `hardware/it8613e/artifacts/it87.ko`, ignored by Git.
- Size: **946448 bytes**.
- SHA-256: **`525cc32659970904024fc177c82d9547f3fe57618000679643391652e537270f`**.
- Prepared `it87.c` SHA-256: **`ccdd098144f8ef99bc40a183c46e1c889e5987c076f6f13478a913307212085f`**.

NAS tmpfs artifacts disappear on reboot. The ignored local copy survives this Live session but is not a repository backup; committed inputs and hashes permit rebuilding. Reproduction is demonstrated on this compiler/header toolchain, not guaranteed across different compilers, debug/BTF tooling or headers. The locally retained binary's checksum matched the NAS result.

## Header/toolchain preparation

**VERIFIED:** initial checks showed:

```text
uname -r: 6.12.107+deb13-amd64
gcc: Debian 14.2.0-19, GCC 14.2.0
make: 4.4.1-2
ld: GNU binutils 2.44 (package 2.44-3)
linux-headers*: no packages installed
apt-cache candidate for exact headers: 6.12.107-1
root: overlay, about 1.8 GiB initially available
/tmp: tmpfs, about 1.9 GiB available
MemAvailable: about 3.2 GiB, no swap
it87: not loaded
```

No APT index refresh, archive/snapshot fallback, distribution upgrade or kernel upgrade was needed. Simulation, including a second root simulation, proposed **0 upgrades, 4 new packages, 0 removals**:

| Newly installed package | Version | Installed size, KiB | Archive SHA-256 |
|---|---|---:|---|
| linux-headers-6.12.107+deb13-common | 6.12.107-1 | 61326 | `12dc292d7c238928fbcb7eebbe79208758fe263a4e2ea0e9b6734e6df12020a5` |
| linux-headers-6.12.107+deb13-amd64 | 6.12.107-1 | 10202 | `0ab746a3d854ad0e666923147842d1e629cdb3e29a97b76ae25b4911285174e4` |
| linux-kbuild-6.12.107+deb13 | 6.12.107-1 | 3094 | `0a88527eb05bca1ce75e7d39ec27539d385a24cf90b2b28917cc4903a4f710d3` |
| pahole | 1.30-1 | 1587 | `08b8b559ab1707dc146880d329f1e96f011788a18d6d3dc7159accd488ae2712` |

APT downloaded 16.4 MB from configured Debian repositories and reported 78.0 MB additional installed space. Existing GCC/Make/binutils and library dependencies sufficed. No kernel-image package was added/upgraded. `apt-get --no-download --no-install-recommends --no-upgrade` installed these explicit versions only, with noninteractive package frontends. This write authorization applied to the ephemeral Live overlay; it did not extend to production storage.

Before installation:

- `dpkg --audit`, non-installed package-state review and the trigger queue showed no pending transaction to repair/complete.
- Downloaded control archives were read without executing them. Only the architecture-specific header package had a postinst; the other three had no maintainer scripts/triggers listed.
- Header postinst calls `linux-run-hooks headers postinst`, which selects header hook directories rather than kernel-image postinst hooks.
- The sole observed header hook was DKMS. The autoinstaller existed, but `/var/lib/dkms` contained no registered modules. No task module was registered with it.
- APT pre-install hooks were apt-listchanges and dpkg-preconfigure; no upgrade/image transaction or device-management hook was selected.

The actual log shows header/kbuild/pahole setup and a **man-db trigger only**; no initramfs, bootloader, firmware, service restart or DKMS module build appears. See [installation evidence](evidence/dependency-install.log) and [script review](evidence/package-script-review.log). Final measurements: root overlay 239 MB used/1.7 GB free, tmpfs 5 MB used, MemAvailable about 3.0 GiB. No cleanup/uninstall was performed: the approved packages remain available in Live RAM.

## Pinned source selection

### Stable baseline

Repository: `gregkh/linux`, tag `v6.12.107`, resolved commit **`f717995cb7dcd8998ab15516b8006aea09cfde0d`**. The exact [baseline driver](https://github.com/gregkh/linux/blob/f717995cb7dcd8998ab15516b8006aea09cfde0d/drivers/hwmon/it87.c) is vendored. It lacks IT8613E, but includes stable backports of several historical it87 improvements. Its downloaded source has 3803 lines; a previously browsed cached tag view had fewer lines, so commit-pinned bytes, not that cached rendering, were used for this work. This is upstream stable source, not a claim that every byte matches Debian's entire source package.

### Accepted mainline series

All three were committed on 2026-10-18:

| Order | Exact commit | Contribution |
|---|---|---|
| 1 | [`28e319062056586c255bac750eca2b595c19c31f`](https://github.com/torvalds/linux/commit/28e319062056586c255bac750eca2b595c19c31f) | Per-chip PWM temperature-map counts |
| 2 | [`ab003112b4948774057bde1c488b0bdbd96d687c`](https://github.com/torvalds/linux/commit/ab003112b4948774057bde1c488b0bdbd96d687c) | Register-map pointer, extended map masks/shifts and correct map handling across modes |
| 3 | [`600a85f556b783b5c619c4b6a576d5b2471be1ca`](https://github.com/torvalds/linux/commit/600a85f556b783b5c619c4b6a576d5b2471be1ca) | IT8613E detection, feature/register configuration and GPIO pin-mux checks |

Mainline history was checked at **`36aad21d50d1af3f6954bb0c988257a908202477`**, dated 2026-10-31. The latest commit touching this driver was 600a85f; no later mainline driver fix appeared in that history. This does not exclude unmerged reports, hardware-specific defects or future fixes. The pinned accepted reference has all three changes together.

The June 2026 negative fan-limit fix **`7f8581c70a3bd50a932d3d2d253e99c5ec3eda74`** and February lock-return fix **`07ed4f05bbfd2bc014974dcc4297fd3aa1cb88c0`** were reviewed in history. The stable baseline already contains the relevant negative-value clamp and lock-error handling; they were retained, not redundantly reapplied. No later IT8613-specific tachometer/GPIO/initialization fix was found after the accepted series at the inspected tip.

**Minimum practical selected set:** these three dependent feature commits on this stable baseline. The second commit is necessary: adding the chip case without its register/mapping infrastructure is incomplete. The final patch initializes the chip's PWM register pointer explicitly.

### Backport adaptations and API compatibility

The consolidated patch carries all changes of those three commits except context for **unrelated IT8689E**, which is absent in Linux 6.12.107. Hunk context near that absent chip was adapted manually, including complete `.reg_pwm`/`.num_temp_map` initialization for IT8628. No IT8689 chip support was added.

**VERIFIED:** after removing only IT8689-specific declarations, descriptor, detection and pin-mux code from the accepted reference, the resulting source is **byte-for-byte equal to the generated backport**. This comparison guards against accidental omissions in manual hunk adaptation. The committed patch applies cleanly to the committed baseline with zero fuzz.

No kernel API shim, signature change, new kernel-interface definition or warning suppression was required. Existing platform-driver, hwmon, devres, I/O-region and PM APIs were retained. The generic PWM-map improvements also affect existing supported chips; therefore this is an experimental replacement for it87, not a claim of regression testing across every ITE model. Only the exact specified Debian ABI was compiled.

### Historical implementation comparison

The older out-of-tree [a1wong source](https://github.com/a1wong/it87/blob/bfbaf881f5bc1462b51e1b0296dba70d0b150515/it87.c) was inspected at **`bfbaf881f5bc1462b51e1b0296dba70d0b150515`**, but is not built or copied into the backport. It advertises six temperature limit/offset resources, unlike the accepted implementation's three known inputs. Its fan5 GPIO-27 bit-1 skip test has the opposite sense from accepted upstream. These concrete differences are reasons not to mix implementations or trust historical parameters blindly. Its source provenance is recorded, not an endorsement of maintenance or RN426 correctness.

Factory baseline: IT8613E revision 3 at base 0xa30; board temp2 about 33 °C, fan2 about 885 RPM, vendor pwm2_enable=3. Those are historical observations under the customized ReadyNAS kernel, not current values or portable mode semantics. The underlying NETGEAR patch source was unavailable; exact vendor/accepted register behavior has not been proved equivalent.

## Static build and module validation

Actual evidence: [first build](evidence/build-first.log), [independent rebuild](evidence/build-reproduction.log), [validation](evidence/validation.log).

```text
CC [M] it87.o
MODPOST Module.symvers
CC [M] it87.mod.o
CC [M] .module-common.o
LD [M] it87.ko
BTF [M] it87.ko
```

Both builds exited successfully with `W=1` and `-Werror`. MODPOST reported no unresolved exports or CRC problems. BTF generation succeeded; it was not disabled to work around an error.

```text
ELF: ELF64, little endian, x86-64, relocatable
name: it87
vermagic: 6.12.107+deb13-amd64 SMP preempt mod_unload modversions
depends: hwmon-vid
license: GPL
signer: empty
srcversion: empty
strong undefined symbols: 40, all present in exact Module.symvers
version CRCs: 41 matched, including module_layout
providers: drivers/hwmon/hwmon-vid and vmlinux
```

Undefined ELF symbols are normal for kernel modules; validation resolves all strong imports against the exact header export table and compares their embedded CRCs. This is static ABI evidence, not actual relocation/loading or proof that dependencies will be available in another running kernel. `hwmon_vid` is present as a stock matching module but **not loaded**. A future load must explicitly arrange that dependency under separate authorization. Source/register accessors use inline port I/O, so the absence of an I/O function import would not prove harmless initialization.

The stock `/lib/modules/6.12.107+deb13-amd64/kernel/drivers/hwmon/it87.ko.xz` SHA-256 before and after compilation was:

```text
24d83d3c9c34894e66f9f6bd6c0f5d316f3d1fb8b050e68988bc5520e9c2ec1f
```

No system module was replaced, no `modules_install`, depmod, DKMS registration or auto-load setting was used. The built module has the **same name and platform driver name `it87`** as stock; it cannot safely coexist as an independent second driver. Ordinary future `modprobe it87` would select stock, not this uninstalled file. Do not force insertion, rename the file to hide a collision, or bypass CRC/vermagic checks.

### Signing and actual boot policy

**VERIFIED:** Legacy BIOS path, EFI sysfs absent, `modules_disabled=0`; lockdown is `[none] integrity confidentiality`. Kernel has MODULE_SIG=y, MODULE_SIG_FORCE disabled, LOCK_DOWN_KERNEL_FORCE_NONE=y. Boot command line has no signature-enforcement override. The built module is unsigned. No active policy requiring signatures was observed in this session; an unsigned external module would normally be permitted but taint the kernel for external/unsigned code. This is not an insertion test and must be rechecked if boot mode/policy changes. No signing keys were accessed.

Final passive check: it87 absent, only acpitz/coretemp hwmon still present, CPU package **35 °C**. Acoustic/full-speed fan behavior was not remotely measurable and is not claimed as a fresh RPM result. No task command changed it.

## Initialization and cooling risk assessment

**SOURCE FACT:** module entry registers a platform driver and probes configuration ports **0x2e and 0x4e**, then constructs a platform device at detected EC base+5/base+6 (historically 0xa35/0xa36 on this RN426). A probe failure does not imply no hardware access occurred; configuration-port selection happens before the EC conflict checks. The stock platform framework can also retain a device whose driver probe failed, so insertion exit status alone is insufficient to claim functioning hwmon.

### Detection, register layout and observations to expect

- Chip ID **0x8613**, revision low nibble, active logical device 4 and nonzero EC base are checked. No forced ID is needed or acceptable for the proposed test.
- GPIO logical-device-7 registers 0x27/0x29/0x2a determine available fan2–5/PWM2–5. Fan1/PWM1 are skipped; fan5 pin-mux bit sense follows accepted upstream, not the historical fork. These checks read pin configuration; they are not GPIO output writes.
- IT8613 uses PWM control registers `{0x15,0x16,0x17,0x1e,0x1f,0x92}` and the separate duty register array. PWM temperature mapping is bits **5:3**, six map sources, not legacy bits 1:0. Only **three temperature inputs and limit/offset sets** are exposed; six mapping selectors do not prove six usable sensors.
- Tachometers use the existing 16-bit count layout and conversion `1350000 / (count * 2)`; zero/0xffff sentinel handling is retained. Actual pulses-per-revolution/board correctness and fan5 handling still need testing. The feature set does not request the older FAN16_CONFIG initialization path.
- The newer driver accepts PWM mode **0 (full duty/manual implementation), 1 (manual), 2 (automatic)**. Factory mode **3 is not accepted** and must not be copied. For this chip, mode 0's implementation sets full duty and manual mode rather than a universal hardware bypass. None of those writes was tested or issued.
- Suspicious polarity/default detection may intentionally hide PWM interfaces. This is a reason to stop, not enable fix_pwm_polarity. Board temperature type/polarity and sensor calibration remain unknown.

### Hardware writes from load and read paths

The following refers to the exact generated source SHA above. It distinguishes normal IT8613 initialization from other-chip or nondefault-parameter branches.

| Path | Write or effect | IT8613 implications |
|---|---|---|
| superio_inb/inw/select | Writes register selector and logical-device selector before reading | Even identification is not literally write-free port I/O |
| __superio_enter / superio_exit | Conditional unlock sequence 0x87/0x01/0x55/(0x55 or 0xaa), exit sequence 0x02 | Configuration mode is changed; both candidate ports may be tried |
| it87_find IT8613 branch | Reads pin mux and beep metadata | No deliberate pin-mux value change in this chip branch |
| it87_check_limit_regs | Any VIN minimum 0xff becomes 0; temperature high limits 0xff become 127 °C | Can alter alarm/protection thresholds merely by loading; firmware use is unproved |
| it87_check_voltage_monitors_reset | VIN_ENABLE 0x50 set to 0xff if initially zero | Enables voltage monitoring, not just exposing an attribute |
| it87_check_tachometers_reset | FAN_MAIN_CTRL 0x13 ORed with selected tach-enable mask if all selected bits were zero | Preserves other bits in source logic; still a controller write with untested board effect |
| it87_check_tachometers_16bit_mode | Can write FAN_16BIT for older feature configurations | Not selected by the IT8613 descriptor; no such write expected for this chip |
| it87_start_monitoring | CONFIG 0x00 written as `(old & 0x3e) | 0x01` with update_vbat=0 | Starts monitoring; bit 6 is cleared, bits 1–5 retained; does not promise fan-policy preservation |
| it87_check_pwm | Read-only by default; fix_pwm_polarity=1 may invert PWM/change FAN_CTL | Dangerous flag must remain false; broken defaults mean stop |
| smbus_disable/enable | Writes special configuration only when chip bitmap is nonzero | IT8613 descriptor has zero bitmap, so no intended SMBus ownership toggle for it |
| Other-chip routing paths | Some supported chips reroute VIN7 pins | Not selected for IT8613; another detected chip could take a different path |
| it87_update_device on sysfs read | Refreshes many sensor/control/limit registers, not only the requested value | Port selectors are written; hardware read-clear semantics/firmware concurrency are not certified |
| Resume callback | Rechecks limits/monitors/tach and starts monitoring again | Later suspend/resume can repeat initialization; no such test authorized |
| Module exit | Unregisters platform devices and driver | No saved-register restore, no full-speed restoration |

The initialization assignments of cached pwm_duty=0x7f and map arrays are **RAM bookkeeping**, not writes that guarantee full fan speed. With safe default parameters, the normal IT8613 init path does not explicitly set PWM duty, switch PWM mode or change PWM polarity. That narrower source fact **does not prove loading cannot affect cooling**: monitoring, tach and limit changes may interact with factory-retained settings or firmware behavior. Sysfs write attributes become available to root, potentially allowing unrelated future software to change settings.

### Current ownership evidence

[Passive I/O evidence](evidence/io-ownership.log) shows active PNP device 00:03, system driver, ranges **0xa00–0xa1f**, **0xa20–0xa2f**, **0xa30–0xa3f**. No loaded it87 or hwmon_vid was present. This does not certify that BIOS/SMI or AML never touches those registers.

The pinned [PNP system driver](https://github.com/gregkh/linux/blob/f717995cb7dcd8998ab15516b8006aea09cfde0d/drivers/pnp/system.c) clears IORESOURCE_BUSY on its container reservations, so the PNP listing alone does **not** prove an exclusive allocation conflict. The backport retains both `acpi_check_resource_conflict` and devm I/O-region allocation. Actual success/refusal is **REQUIRES TEST**. Do not use ignore_resource_conflict or acpi_enforce_resources=lax to turn a failed test into a successful one. No resource policy was changed.

**Unresolved cooling risks:** exact factory limit semantics, temperature types, fan tach calibration, firmware/SMI concurrency, retention across power/reset, and a verified full-speed recovery path. Prior factory fan2=885 RPM and PWM mode 3 are insufficient to derive a safe restore command. A loud fan is not an independently verified full-duty fail-safe.

## Proposed supervised first-load experiment

**Not executed. Not authorization to load.** No fan-speed reduction is part of this first test. The present production-connected NAS should remain at its existing behavior. Because controller rollback is unresolved, the recommendation now is **additional source/board-recovery investigation**, followed by a separately approved isolated test.

### Gates before authorization

1. Arrange a separately authorized powered-off maintenance window and physically disconnect all six production HDDs; keep order and key media preserved. Preserve the factory module. Their MD read-only flag is not a substitute for isolation. No power action/disconnection was performed in this task.
2. Review the write table against vendor source or equivalent board documentation, especially CONFIG/limit/tach writes and firmware ownership. Establish a **known working independent cooling/recovery method** before inserting anything. This could require a separately planned hardware airflow intervention or previously validated exact-board full-duty recovery; do not assume reboot or power cycling restores safe settings.
3. Have an on-site operator and UART access. Coretemp must work and remain visible independently of it87. Establish sensor/airflow abort thresholds and an agreed emergency power procedure. No stress load or unattended run.
4. Verify exact running ABI, artifact SHA, available exact dependencies, no loaded it87, no conflicting fan daemon, no autoload policy, and unchanged module-security policy. Keep all override flags false and force_id absent. If any prerequisite is unclear, do not start.

### Conditional execution plan for a later authorized session

These are future operations, **none run now**:

1. Record coretemp and physically observed airflow/sound for about one minute. Record existing hwmon names and relevant boot-log tail. Do not read production devices.
2. Explicitly authorize loading the stock matching **hwmon_vid** dependency first (pure conversion helper), then insertion of the **exact absolute-path experimental artifact** once. Its intended parameters are `fix_pwm_polarity=0 ignore_resource_conflict=0 update_vbat=0`, with **no force_id**. Do not use ordinary `modprobe it87`, which selects stock. Do not register this artifact for automatic loading.
3. Watch UART/kernel messages during insertion. Expected evidence is an IT8613E identification at the actual base/revision and a new hwmon device named `it8613`. Revision 3/base 0xa30 are historical expectations, not values to force. Any second/unexpected chip, ACPI conflict, allocation failure, hang, polarity warning or missing device is an abort condition. Exit status 0 alone is insufficient.
4. Read only whitelisted attributes of that device: name, existing temp1–3_input/type, fan*_input, pwmN, pwmN_enable and mapping values. No writes, sensors-detect, sensors -s, generic controller scans or automatic fan daemon. Observe CPU/valid board temperature and RPM roughly once per second for **30 seconds**, at most **60 seconds** for the initial observation.
5. Expected observations are a plausible board sensor, one or more stable tach readings (historically fan2), and PWM interfaces/modes consistent with source. Invalid -128 °C channels, zero tach on unused inputs and hidden PWM may occur; do not enable unknown sensors, pins or controls to make the result look complete. No reduction is allowed regardless of apparently good data.
6. Stop on unexpected fan slowing/stall/airflow loss, unstable/missing tach, sensor invalidity on the monitored cooling channel, CPU package **50 °C** or **5 °C above pre-load baseline**, or new errors. These are conservative proposed trial limits, not certified RN426 thermal specifications. Agree valid board-temperature limits before the trial.

### Recovery and completion

On an abort, use the **pre-established independent cooling method** and agreed on-site procedure immediately. Ending reads or unloading the module does not restore registers. If physical intervention or power action would be needed, that must already have separate authorization; never improvise register values or assume reset recovers airflow. If no such recovery route is available, this gate fails and **there should be no first load**.

Even a successful observation is only sensor/interface validation. Whether to leave the module temporarily resident or remove it must be decided under the test authorization; removal releases software ownership but does not roll hardware back. Re-read core temperatures and physically confirm airflow afterward. Keep a record of the actual board state before any later PWM write proposal. Fan-speed reduction, automatic curves, crash/daemon fail-safe, suspend/resume and unattended operation are separate future experiments.

## Remaining limitations and next authorization

- Static ABI success is established; real initialization, sensor accuracy, fan mapping and PWM operation are not.
- The accepted implementation is recently merged. No subsequent mainline fix was found at the pinned history tip, but no RN426 qualification evidence was found either.
- Vendor mode 3, board wiring, register ownership and power/reset retention remain unresolved. No vendor source was obtained in this task.
- No source feature was added to suppress init writes: that would be a separate design requiring review, not an unexamined safety flag.
- Current protected production storage was not inspected. Its strict-RO status is inherited operator context, not a fresh assertion from this task.
- User-space policy, thermal curves and enclosure/GPIO support remain outside this build; this driver does not replace readynasd or fix Denverton GPIO.

**Next operator authorization needed:** after recovery questions are resolved, a maintenance window for production-disk isolation and a single supervised insertion including initialization writes and the hwmon_vid dependency. It must explicitly cover the on-site recovery contingency. It should **not** include fan-speed reduction. No load approval was sought or assumed during preparation.

## Commands and safety record

Collection used the previously confirmed target over password-only SSH with agent forwarding disabled; the matching Live host-key fingerprint was observed again. No credential was stored. The local SSH transport was closed after work.

Executed command categories:

- Required toolchain/header checks: uname, compiler/make/ld versions, dpkg-query, apt-cache policy, apt-get simulations, df/free and root/tmp mount-type checks.
- Package review: apt-config hook entries, dpkg audit/trigger state, header-hook/DKMS script text, downloaded dpkg control tar listing/script reads, exact archive checksums. No maintainer script was run manually.
- Authorized mutations: download/install the four pinned packages into overlay; create user-owned temporary build files on tmpfs; compile twice as user. No root build or permanent task-module installation.
- Validation: modinfo/readelf/nm, exact header config and Module.symvers, module-security sysfs/proc fields, stock/new file checksums, source equality and byte comparison, current coretemp readings and I/O/PNP ownership metadata.
- Local-only work: public kernel-source/history downloads, patch adaptation, build/validation code, artifact copy, documentation and Git operations. Public APIs received no private NAS data.

No insmod/modprobe was executed. No driver bind, direct port/Super I/O register access, module-control action, GPIO/I2C probing, fan write, restart, reboot, initramfs/bootloader update, network reconfiguration, stress test or disk/MD/LUKS access was performed. Existing services continued operating. Ordinary SSH/sudo logging and authorized ephemeral package/build writes are the intentional system changes in scope.
