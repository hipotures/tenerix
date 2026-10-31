# RN426 front panel on Debian 13 Live

Date: 2026-10-31. Target: NETGEAR ReadyNAS 426, Atom C3538, Debian 13.7 Live, kernel `6.12.107+deb13-amd64`.

**VERIFIED:** the operator saw **Debian 13 / RN426 ready** on the OLED. All five navigation buttons generated recognized events. The operator also confirmed the display changed to **Button / direction**, including **CENTER** for the middle button. The bounded test captured 16 events and 16 MCU reads; all five buttons appeared at least twice. A small reusable Python interface and JSON event CLI are provided here. No service was installed or enabled.

The existing IT8613E module was already loaded when this task began. This task did not load, unload, replace or configure it. The earlier [driver build report](../it8613e/README.md) describes an earlier preparation-only phase; its historical statement that the module was not loaded is not a description of this later session. The [factory audit](../../readynas-rn426-audit.md) and [Debian audit](../../readynas-rn426-debian13-audit.md) are hardware baselines, not overwritten findings.

## Files and pinned dependency

| File | Purpose |
|---|---|
| `panel.py` | RN426-only safety adapter, synchronous API and CLI |
| `test_panel.py` | Software tests using fake MMIO/MCU boundaries |
| `fetch-upstream.py` | Fetch and verify the immutable reviewed dependency locally |
| `provenance.json` | Exact upstream commit and runtime file SHA-256 hashes |
| `LICENSE` | Preserved upstream MIT license; local adapter is also MIT |
| `evidence/session.log` | Sanitized actual measurements, events and operator confirmations |
| `.upstream/` | Ignored local dependency checkout; no Git submodule or unpinned download |

Upstream: [riplatt/truenas-rn426-panel](https://github.com/riplatt/truenas-rn426-panel), pinned to **`2968ee0514908d44b076ed1120f385a338bf1cd2`**, commit subject `README: RN428 confirmed working by a tester (issue #3)`.

Read and reviewed: README, `docs/debian-omv.md`, `docs/lcd-protocol.md`, `docs/buttons-protocol.md`, `docs/reverse-engineering.md`, `rn426_panel.py`, models, both GPIO backends, LCD, I2C, MSP430, app, panel test and test utilities. Attribution: the renderer, SPI transport, pad map, MCU protocol and interrupt/debounce algorithm come from that MIT-licensed project. This integration subclasses its implementation instead of vendoring or rewriting the driver.

**Important upstream discrepancy:** this exact commit's docs say never lower EN, but `MODELS["rn426"]["en_can_pulse"]` is `True`, and `LCD.init()` explicitly lowers EN when true. Upstream even tests that behavior. Its passing tests therefore do not establish suitability for this task. **Do not run the unadapted upstream CLI, `test`, `app.run`, installer or service.** Our adapter supplies `en_can_pulse=False` and independently rejects EN/RST-low writes at the final MMIO write boundary.

The documentation also contains stale references to other models and an unrelated fan-chip identification. Exact live RN426/Denverton identity and the existing IT8613E measurements take precedence. No other model is supported by this adapter.

## Reproduce the software preparation

On the development computer, from this directory:

```sh
python3 fetch-upstream.py
python3 -m unittest test_panel -v
python3 -m unittest discover -s .upstream/tests -v
```

Fetching clones public source and checks out the exact commit. It installs nothing and performs no hardware access. The six runtime Python modules are hash-checked before import. `rnpanel.app`, `pages`, SX8635 tools and all installers are excluded from the runtime import graph. The local checkout remains ignored; committed provenance permits reproducing it. The copied license is retained independently of the checkout.

**Actual software results:** upstream **318/318 tests passed** locally before hardware access. Final adapter **10/10 tests passed** locally and on the NAS. Tests cover real upstream LCD initialization through fake MMIO, write allowlisting, preserving configuration bits, refusing unsafe initial levels, model override refusal, one read per IRQ assertion, 50 ms rearming, all five mappings, stuck-low startup, visible I/O failure, unknown bitmaps, duration bounds, missing I801 refusal and exclusive ownership before GPIO access. These are simulated boundaries, not fabricated hardware events.

## Live dependencies and environment

| Component | Actual result/action |
|---|---|
| Python | 3.13.5, already installed |
| Pillow | Missing initially; installed `python3-pil` **11.1.0-5+deb13u4**, reports 11.1.0 |
| Font | `fonts-dejavu-core` **2.37-8**, already installed; both required Mono fonts present |
| Additional new packages | `libraqm0` **0.10.2-1**, `libwebpdemux2` and `libwebpmux3` **1.5.0-0.1** |
| I801 | `i2c_i801` already loaded; adapter `SMBus I801 adapter at f000` |
| I2C character interface | `i2c-dev` initially absent; dry-run reviewed, then loaded once with `sudo -n modprobe i2c-dev` |
| Device nodes | `/dev/mem` present; after i2c-dev, `/dev/i2c-0` and `/dev/i2c-1` present |
| Process ownership check | `fuser` from existing psmisc available; no existing `/dev/mem` owner or panel process before test |
| Resources | Root overlay 1.7 GiB available, `/tmp` tmpfs 1.9 GiB available; MemAvailable about 3.0 GiB |

APT simulation: **0 upgrades, 4 new packages, 0 removals**, download 766 kB, additional installed size 2,289 kB. No APT index refresh was needed. `dpkg --audit` reported no pending issue. Downloaded package control archives were reviewed before installation: Pillow's postinst only runs Python bytecode compilation; the libraries activate ldconfig. No service, kernel image, initramfs, bootloader or hardware hook was selected. Actual installation processed only the libc-bin trigger. The inspection command returned status 2 because optional postrm/triggers entries were absent from some archives; listed available scripts were inspected, not executed by that inspection.

The exact package transaction was:

```sh
sudo -n apt-get -s --no-install-recommends --no-upgrade install python3-pil
sudo -n apt-get --download-only --no-install-recommends --no-upgrade -y install python3-pil
# Inspect each downloaded package using dpkg-deb --ctrl-tarfile and tar listing/extraction to stdout.
# Confirm / is overlay and /tmp is tmpfs before installation.
sudo -n env DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none \
  apt-get --no-download --no-install-recommends --no-upgrade -y install \
  python3-pil=11.1.0-5+deb13u4 libraqm0=0.10.2-1 \
  libwebpdemux2=1.5.0-0.1 libwebpmux3=1.5.0-0.1
sudo -n modprobe -n -v i2c-dev
sudo -n modprobe i2c-dev
```

These preparation actions were explicitly authorized for Live RAM. They are not performed automatically by the integration. Only `i2c-dev` was added; no existing module was replaced or reconfigured. For a later OS/session, review its dependencies and policy afresh rather than replaying package commands blindly.

## Hardware identity and write review

**VERIFIED:** DMI vendor `NETGEAR`, product and board `ReadyNAS 426`; CPU `Intel(R) Atom(TM) CPU C3538`; Denverton LPC/eSPI **8086:19dc**, PCI `00:1f.0`. The wrapper requires all these facts, agreement with upstream model detection, and absence of `RN_MODEL`. It does not accept forced model overrides or CPU-only identification.

Both Denverton communities reported **PADBAR 0x400**. The preflight checks all seven pads for GPIO mode and all six output pads for enabled output drivers. It additionally requires EN/RST already high; it will not try to recover a low line. Actual preflight:

| Signal | Physical PADCFG_DW0 | Value before first write | Allowed operation |
|---|---|---|---|
| EN | `0xFDC20418` | `0x05000201` | High only |
| CLK | `0xFDC20470` | `0x05000201` | SPI clock TXSTATE |
| MOSI | `0xFDC20480` | `0x05000200` | SPI data TXSTATE |
| RST | `0xFDC20488` | `0x05000201` | High only |
| D/C | `0xFDC50580` | `0x45000201` | SPI command/data TXSTATE |
| CS | `0xFDC505C8` | `0x45000201` | SPI chip select TXSTATE |
| MCU IRQ | `0xFDC50570` | `0x43080102` | Read RXSTATE bit 1 only, active-low |

These reproduce the pinned upstream RN426 map. Factory logs previously identified `gpio_dnv.0:5` as front-board IRQ and I801 client **0x1c**. The original audit did not independently derive physical pad offsets; that mapping comes from upstream's reverse engineering and is now supported by successful display/button operation. Mainline GPIO numbering is not substituted for vendor numbering.

**Write boundary:** only the six listed display-pad DW0 addresses are writable. The IRQ pad is not in the allowlist. Only TXSTATE bit 0 is deliberately changed. Unlike upstream's `_set`, the adapter **preserves RXDIS bit 9** and all other configuration bits. The final write guard rejects changed configuration and any EN/RST-low value. RXSTATE bit 1 is read-only and may change between reads. No P2SB unhide, PCI write, `/dev/port`, Super I/O, ITE/fan controller, arbitrary MMIO, GPIO mux change or I2C scan occurs.

**LCD initialization:** upstream SSD1305 33-byte command sequence, no reset pulse, then EN high and display-on `0xAF`. Commands/data are bit-banged over the reviewed pads. Sleep sends **0xAE only**; wake sends **0xAF only**. Clear sends a blank frame. No MCU register is written.

**Button path:** exactly one named I801 adapter must exist; missing/ambiguous adapter is fatal rather than upstream's fallback to bus 1. Bind normally to address **0x1c**, never with force. Watch only the documented IRQ pad about every 5 ms. After at least 50 ms continuously inactive, the next assertion allows one SMBus **read-byte-data of register 0x04**. Read again only after rearming. Startup is deliberately unarmed, preventing a stuck-low IRQ from triggering an initial read. Direct `pressed()` use is rejected. Unexpected bitmap bits and I/O errors stop visibly rather than being silently treated as no press. No continuous I2C polling and no write to **0x02**, or any MCU configuration register, is implemented.

## Actual hardware results

The reviewed files were transferred over SSH into user-owned **`/tmp/rn426-panel.Cg0ucU`**, verified to be tmpfs. No source or result file was written to production storage. Runtime files and dependencies disappear with the Live session. This directory is retained for current-session use; no service remains running.

Commands below were actually run there, with bytecode caching disabled:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_panel -v
sudo -n env PYTHONDONTWRITEBYTECODE=1 python3 panel.py preflight
sudo -n env PYTHONDONTWRITEBYTECODE=1 python3 panel.py show 'Debian 13' 'RN426 ready'
sudo -n env PYTHONDONTWRITEBYTECODE=1 python3 -u panel.py buttons --seconds 300 --echo
```

1. **VERIFIED:** read-only preflight passed with the values above. The final post-test preflight reported the same values.
2. **VERIFIED:** first text frame sent without error. **OPERATOR-CONFIRMED:** both requested text lines visible. Final-version frame transmission measured **158.15 ms**; this does not include constructor/initialization time.
3. **VERIFIED:** the five-minute-maximum listener produced the following mappings/counts. The operator confirmed direction labels changed on the OLED, including CENTER. After success it was ended early using SIGTERM on the exact PID after checking its cwd and full command line. Exit status 0; summary printed and handles released. No unrelated process/service was stopped.

| Physical button | Raw bitmap | Upstream action | Public event | Actual events |
|---|---|---|---|---:|
| LEFT | `0x01` | LEFT | LEFT | 2 |
| RIGHT | `0x02` | RIGHT | RIGHT | 4 |
| UP | `0x04` | PREV | UP | 2 |
| DOWN | `0x08` | NEXT | DOWN | 2 |
| CENTER | `0x10` | OK | CENTER | 6 |

The capture contains **16 MCU reads / 16 recognized events**. It demonstrates repeated real presses for all five buttons. There was no synchronized physical press counter, so exact missed-event rate, long holds, fast repeated presses and long-term reliability remain **UNKNOWN**. Display redraw blocks button watching for about one frame; about one second between test presses was requested.

4. **VERIFIED at command/API level:** final wrapper `sleep()`, `wake()`, `clear()`, then `show("Debian 13", "RN426 ready")` completed in one exclusive owner context. Shared-line guards remained active. Individual visual off/on/blank transitions were not separately confirmed, so their physical appearance remains **UNVERIFIED**.
5. **VERIFIED:** final-version 15-second idle listener: all event counts **0**, MCU reads **0**. No sleeping-MCU polling was observed by the software read counter.
6. **VERIFIED:** final `fuser` reported no open `/dev/mem` or I801 handles, no Python panel process remained and `systemctl --failed` was empty. Relevant recent kernel log filter showed the pre-existing external it87 load and the expected i2c-dev registration, with no new relevant error. A filtered log cannot prove absence of every possible hardware issue.

Passive temperature/tachometer readings remained available: CPU package **37 → 38 → 37 °C**, IT8613 temp2 **31 °C** throughout; fan2 **1520 → 1516 → 1979 RPM**. The RPM varied; no constant-speed claim is made and its cause was not established. The task issued no fan/PWM/thermal writes and did not alter module parameters. Existing invalid temp1/temp3 (-128 °C) and ACPI 0 °C readings were not used as valid temperatures.

The initial hardware run used the same no-EN-pulse and bit-0-only adapter, with eight safety tests. Later hardening added a general `/dev/mem` owner check, unknown-bitmap rejection and failure-path resource cleanup; final ten-test version was retested on the NAS, sent another text frame and completed the API/idle tests. The 16 physical events came from the initial supervised run, not the final idle run; the underlying upstream interrupt/debounce algorithm is unchanged.

## Reusable API and CLI

Run from this directory with the verified `.upstream` dependency and reviewed device permissions. No command fetches dependencies, installs packages or enables services automatically.

```sh
sudo python3 panel.py preflight
sudo python3 panel.py show 'Your text' 'Second line'
sudo python3 panel.py clear
sudo python3 panel.py sleep
sudo python3 panel.py wake
sudo python3 -u panel.py buttons --seconds 120
sudo python3 -u panel.py run --seconds 120 --echo
```

`preflight` reads the identity/pads only; it does not initialize the LCD. Other commands create one exclusive panel owner and initialize the LCD safely. Thus a standalone `sleep` command briefly initializes before pixels-off; within a long-running `Panel` object, `sleep()` and `wake()` are only their respective display commands. Each one-shot command exits cleanly, preserving the last image/state rather than resetting the front board. There is no automatic idle-sleep policy or daemon; a future management application can call `sleep()` after inactivity.

Python integration:

```python
import time
from panel import Panel

with Panel() as panel:
    panel.show("Debian 13", "RN426 ready")
    # Application-owned event loop; all panel methods use the same owner/thread.
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        for button in panel.buttons():
            panel.show("Button", button)
        time.sleep(0.005)
```

`show(line1, line2)`, `clear()`, `sleep()`, `wake()`, `buttons()` and bounded `run(seconds, echo)` are synchronous. `buttons()` returns a list of public names for one tick, with no wait; calling it periodically watches MMIO, not periodically reading SMBus. Keep one owner and serialize calls; it is not a thread-safe API. Text uses the upstream fixed font/geometry and clips at panel edges rather than wrapping. No temperature, fan or storage pages are imported.

For a Rust application, a bounded `buttons` child emits one JSON object per line (startup, button events, final counts). Treat nonzero exit status/stderr as failure. One-shot `show` is suitable when that child is absent. **Do not launch `show` beside a button listener.** For simultaneous application-controlled text and button handling, use one Python owner integrating both operations as in the example; adding a multiplexed IPC protocol can be a later application decision.

Ownership is guarded by `/run/lock/rn426-panel.lock`, upstream service status and a pre-open `fuser /dev/mem` check. A second cooperative owner is rejected before GPIO initialization. It does not lock out arbitrary programs bypassing this interface; never run another raw panel/GPIO controller concurrently. The lock file may remain in Live RAM after exit; its advisory lock is released by closing the FD. Do not manually remove it to bypass an active owner.

## Safety boundaries and remaining work

- **Never run unadapted RN426 upstream initialization at this pin.** EN-low is an actual source path despite the documentation warning. The adapter independently refuses it.
- **Never lower EN/RST, write MSP430 0x02, poll 0x04 without IRQ, force a model, force I2C ownership, scan addresses or broaden the MMIO allowlist.** No recovery/reset fallback is provided. A failure stops the test.
- Failed model/pad/ownership checks require investigation. Do not bypass them or use tools from upstream's reverse-engineering directory on this production-connected NAS.
- Upstream reports a wedged MCU can require removal of AC power and that warm reboot may not fix it. That recovery was neither needed nor authorized here. No cold cycle/reboot/reset was attempted.
- Production HDDs, MD, LUKS, Btrfs and internal factory USB were not inspected, mounted, unlocked or modified. No storage queries were used for display content. No network/SSH, boot, firmware or automatic-service configuration was changed.
- Direct MMIO remains privileged, board-specific experimental userspace hardware access. It bypasses the GPIO framework and does not coordinate with a future kernel driver/firmware owner. The existing Debian baseline had no active Denverton GPIO chip; a different kernel must be reviewed before reuse.
- Long-term button reliability, fast input during redraw, idle burn-in policy and additional application UX remain to be tested. The current bounded test proves all requested physical buttons and custom text; it does not qualify unattended production operation.

## Inspection/experiment command record

All NAS commands were issued from the development computer over SSH as `user`, with individual sudo operations where needed. Host address/credentials and unrelated device identifiers are intentionally omitted. Source/tests/output captures were local or in the approved tmpfs directory.

| Operation | Commands/interfaces actually used | Result |
|---|---|---|
| Baseline review | `cat`/`rg` existing repository reports and AGENTS.md | Historical observations preserved |
| Source review | Public `git clone`, `git rev-parse HEAD`, `git log -1`; source/docs reads; public repository web view | Exact commit pinned; unsafe EN pulse found |
| Identity/dependencies | `uname -r`, `python3 --version`, selected DMI files, `lscpu`, `lspci -nn -s 00:1f.0`, import PIL, selected `dpkg-query`, font/device listings | RN426/Denverton confirmed; missing Pillow/i2c-dev |
| Existing ownership | `ps` filtered to panel/Python, `systemctl is-active rn426-panel`, `fuser -v /dev/mem` | No prior controller |
| Resources and modules | `findmnt -T /tmp` and root FSTYPE, `df`, `free`, filtered `lsmod`, I2C adapter name files | Live RAM; I801 pre-existing |
| Package preparation | Simulation/download, `dpkg --audit`, `dpkg-deb --ctrl-tarfile` with tar to stdout, exact pinned install above | Four new packages; no upgrade; libc-bin trigger only |
| Interface preparation | `modprobe -n -v i2c-dev`, then `modprobe i2c-dev`; `/dev/i2c-*` listing | Character interfaces created; no controller reset |
| Source transfer | Guarded tmpfs `mktemp -d`, tar over SSH into that directory | No persistent NAS install |
| Software verification | Upstream unittest locally; adapter unittest locally and unprivileged on NAS | 318 upstream / 10 final adapter pass |
| GPIO preflight | `sudo python3 panel.py preflight` twice | Same safe values before/after |
| LCD | `show` twice; one-context sleep/wake/clear/show | Text visually confirmed; final frame 158.15 ms |
| Buttons | Bounded `buttons --seconds 300 --echo`, then final 15-second API idle loop | 16 events; final idle 0 reads |
| Stop owned test | Verify exact PID command/cwd using `/proc`, then `kill -TERM` that PID | Clean summary/exit, no unrelated process stopped |
| Post-check | `fuser`, filtered `lsmod`, `systemctl --failed`, filtered recent `journalctl -k`, named hwmon temp/tach reads | No residual panel owner or failed unit; existing monitoring available |

No secrets or raw production identifiers are included in committed evidence. The implementation and evidence are committed to the current project branch; the upstream checkout and caches are ignored.


## Alpine 3.24 support (2026-10-31)

The existing API and CLI now support OpenRC and Alpine's native DejaVu paths.
`PanelLCD` retains upstream rendering and transport; only font construction changes.
The pinned upstream checkout and MIT attribution are unchanged. The service check
uses `rc-service rn426-panel status` when an OpenRC service exists, accepting only
stopped status 3. With no such service, the exclusive flock and mandatory full
`fuser -s /dev/mem` check still apply. Unknown init environments, missing tools,
active services and indeterminate status fail closed. No service is installed,
started or stopped. Preflight takes the same exclusive lease before mapping.

Debian systemd ownership checks remain supported. Both regular and bold Mono
fonts must exist together in `/usr/share/fonts/truetype/dejavu` (Debian) or
`/usr/share/fonts/dejavu` (Alpine). No upstream hash guard, EN/RST protection,
GPIO configuration protection or interrupt-triggered MSP430 restriction changed.
`/dev/mem` security restrictions are never weakened.

Actual RN426 Alpine results: OLED text visually confirmed; all five buttons
observed in nine events. Thirteen safety tests pass on the development host,
Alpine container and NAS. See [complete hardware evidence and commands](../alpine-hardware-test/README.md).
There is no automatic service or hardware probe added by this port.
