# Alpine 3.24.3 RN426 serial-console Live ISO

Built and tested on the development computer on 2026-10-31. **No connection to the NAS, physical-device write, host package installation or distribution upgrade was performed.** Baselines: [RN426 boot audit](../../readynas-rn426-boot-audit.md) and [Debian UART evidence](../../readynas-rn426-debian13-audit.md).

## Finished artifact

- ISO: `artifacts/alpine/alpine-3.24.3-rn426-serial-x86_64.iso`
- Checksum: same path plus `.sha256`.
- Size: **370475008 bytes (353.3125 MiB)**.
- SHA-256: **`4be8e8b22510bb3dd17693e4383fea31a0cbc06bd9335bf476255708a5dd9c8e`**.
- **VERIFIED:** two independent builds are byte-identical, using fixed timestamps and the original GPT disk GUID.
- Large images, extracted trees, raw serial captures and intermediates are ignored under `artifacts/alpine/`; scripts and readable evidence are committed.

**VERIFIED:** headless QEMU Legacy BIOS CD-ROM and USB boots both reach an interactive **ttyS0 login** without bootloader input. After typing `root`, the official Live account opens a shell; `uname -a`, `/proc/cmdline`, inittab, `tty`, UID and 115200-baud settings were checked. This is an ordinary login, not an automatic shell. **RN426 hardware success remains UNTESTED** for this rebuilt image.

## Official baseline and inspection

Original, retained unchanged: `artifacts/alpine/original/alpine-standard-3.24.3-x86_64.iso`.

- [Exact official ISO URL](https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-standard-3.24.3-x86_64.iso).
- [Official SHA-256 file](https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-standard-3.24.3-x86_64.iso.sha256).
- Verified original SHA-256: **`1629ffe7308d4f3d3eeeed3a97d09ad62293f6d37ef3e483a7306077fdac12be`**.
- Embedded `.alpine-release`: **`alpine-standard-3.24.3 261021`**; guest `/etc/alpine-release`: **3.24.3**.
- Original kernel: **6.18.58-0-lts**; original init script version: **mkinitfs 3.14.1-r0**.
- HTTPS/published checksum verified; optional detached-signature verification was not performed.

| Item | Discovered source layout |
|---|---|
| BIOS configuration | `/boot/syslinux/syslinux.cfg`, default label `lts` |
| Kernel/initramfs | `/boot/vmlinuz-lts`, `/boot/initramfs-lts` |
| Original arguments | `modules=loop,squashfs,sd-mod,usb-storage quiet` |
| BIOS loader | `/boot/syslinux/isolinux.bin`, banner ISOLINUX 6.04 / 6.04-pre1 |
| El Torito catalog | `/boot/syslinux/boot.cat`; BIOS no-emulation entry, four load sectors |
| Hybrid boot | ISOLINUX-compatible MBR, active partition, GPT, cylinder alignment |
| UEFI | Second El Torito entry, `/boot/grub/efi.img` (2880 sectors), `/efi/boot/bootx64.efi` |
| EFI Linux entry | `/boot/grub/grub.cfg` |
| Diskless root | Initramfs locates boot media, installs original local APKs into tmpfs root; original modloop is mounted read-only |

Original versus modified configurations are saved in [`evidence/`](evidence/). The build extracts and checks the actual image layout; it does not assume a generic `isolinux.cfg` path.

## Changes: bootloader, kernel, login

The BIOS configuration starts with this serial directive, before any other directive:

```text
SERIAL 0 115200 0
CONSOLE 1
NOHALT 1
TIMEOUT 30
TOTALTIMEOUT 30
PROMPT 1
DEFAULT lts
ONTIMEOUT lts
```

`SERIAL` enables bootloader COM1 input/output at 115200, fixed 8N1; flow mask 0 avoids CTS/DSR/DCD requirements. `CONSOLE 1` retains VGA output. `NOHALT 1` improves polling responsiveness during the short bootloader interval. Both timeout values are **30 deciseconds = three seconds**; TOTALTIMEOUT also bounds delays from stray input. The existing `lts` label, kernel/initrd and FDT directory are preserved.

**Why PROMPT 1:** with one label, Syslinux documents that PROMPT 0 can bypass TIMEOUT and boot immediately. PROMPT 1 supplies the requested short wait and accepts serial input; **nothing must be typed**. The separate no-input CD/USB tests demonstrate automatic boot. See [upstream Syslinux SERIAL/PROMPT/TIMEOUT documentation](https://wiki.syslinux.org/wiki/index.php?title=SYSLINUX).

Both BIOS APPEND and GRUB's Linux line retain all original module arguments, remove only `quiet`, and append:

```text
console=tty0 console=ttyS0,115200n8
```

GRUB keeps the existing entry, with default 0 and timeout three seconds. Its kernel receives serial output/login settings; EFI bootloader serial-menu input itself is not configured or claimed tested.

**No apkovl needed.** The exact unmodified initramfs parses `console=`, resolves active console aliases, and invokes `setup_inittab_console` after setting up the tmpfs root. It adds an active entry:

```text
ttyS0::respawn:/sbin/getty -L 0 ttyS0 vt100
```

Baud 0 preserves the kernel's **115200** setting; `-L` provides a local line without modem carrier requirements; terminal is **vt100**. The original commented 115200 example in inittab is distinct from this generated active line. Existing tty1–tty6 gettys remain. The function also adds a console to `/etc/securetty` if needed; this image already supplies ttyS0 there. Actual serial root login verifies the complete path. No credentials/accounts, autologin, SSH enablement or network configuration were added.

Exact-source excerpts and source/initramfs hashes are in [`initramfs-console.txt`](evidence/initramfs-console.txt) and [`build-manifest.json`](evidence/build-manifest.json). The current upstream [mkinitfs source](https://github.com/alpinelinux/mkinitfs/blob/master/initramfs-init.in) is supporting context; the script extracted from the checksum-pinned ISO is the evidence for this version.

## Reproduce without host package changes

Requirements on the development machine: Python 3, network access for the initial downloads/container build, and working rootless Podman. Run from the repository root:

```sh
python3 hardware/alpine-serial/build.py --fetch-only
podman build -t localhost/tenerix-alpine-serial-tools:3.24.3 \
  -f hardware/alpine-serial/Containerfile hardware/alpine-serial
podman run --rm --network none --userns keep-id \
  -v "$PWD:/workspace:rw" localhost/tenerix-alpine-serial-tools:3.24.3 \
  python3 hardware/alpine-serial/build.py
```

The build refuses to overwrite an existing output or write outside `artifacts/alpine`. For an independent rebuild, add `--output artifacts/alpine/reproduce-2.iso`, then use `cmp` against the delivered ISO. It rechecks both the published and pinned checksum before any repack; the original is never edited.

The tool container uses the official Alpine 3.24.3 image pinned by digest in `Containerfile`. Direct tool versions are pinned: xorriso **1.5.8-r0**, QEMU **11.0.3-r0**, SeaBIOS **1.17.0-r0**, Python **3.14.10-r1**, pexpect **4.9-r2**, cpio **2.15-r0**. Full resolved versions are in [`tool-packages.txt`](evidence/tool-packages.txt); dependent repository packages are not all individually pinned, so future archive availability must be considered when recreating the container. No host packages were installed. The offline build and VM containers have no network access or physical-device passthrough.

xorriso imports the original image, maps the two replacement config files and uses **`-boot_image any replay`**. It preserves the volume label, original GPT GUID and boot arrangement; timestamps are fixed to `2026102100000000`. It then re-extracts and compares every ISO file. **110 payload files are unchanged**, including kernel, initramfs, modloop, all APKs, EFI FAT image and EFI executable. Only the two configs, generated boot catalog and ISOLINUX boot-info-table bytes change. Bytes outside the loader's boot-info table are checked unchanged. Original/output El Torito and system-area reports are committed.

Expected repack warnings concern the inherited volume label `alpine-std 3.24.3 x86_64` containing lowercase/spaces. Both BIOS/UEFI boot entries and the hybrid MBR/GPT are retained. File LBAs move, so catalog/table pointers are correctly regenerated, not copied blindly. xorriso's output includes trailing padding; the tested hybrid boot extent is preserved.

## Actual QEMU validation

No KVM device exists here; tests used **TCG**, x86_64, two vCPUs and 2048 MiB RAM. All modes use `-display none -serial stdio -monitor none -nic none -no-reboot`. The only medium is the generated ISO, opened **readonly=on**. Root is guest tmpfs; there is no writable disk or physical storage passthrough.

Repeat the two automatic-boot tests in the same offline tool container:

```sh
podman run --rm --network none --userns keep-id -v "$PWD:/workspace:rw" \
  localhost/tenerix-alpine-serial-tools:3.24.3 \
  python3 hardware/alpine-serial/qemu-test.py --mode cdrom
podman run --rm --network none --userns keep-id -v "$PWD:/workspace:rw" \
  localhost/tenerix-alpine-serial-tools:3.24.3 \
  python3 hardware/alpine-serial/qemu-test.py --mode usb
```

CD uses a read-only IDE virtual CD and SeaBIOS. USB uses xHCI plus read-only `usb-storage` with bootindex 1, independently exercising the MBR/ISOHybrid disk path. The test script sends **no input before login** in either mode. It waits for kernel messages and a login prompt, logs in, verifies actual shell output, then powers off **only the guest**.

| Test | Measured outcome |
|---|---|
| BIOS CD, no bootloader input | **PASS**, login at **31.74 s**, complete test **38.01 s** |
| BIOS USB, no bootloader input | **PASS**, login at **32.64 s**, complete test **38.51 s** |
| ISOLINUX serial-input test | **PASS**, typed `lts` echoed/accepted at `boot:`, serial login at **29.38 s**, complete test **35.78 s** |
| ttyS0 shell | **PASS**, root UID 0, `tty` = `/dev/ttyS0`, uname **6.18.58-0-lts**, release **3.24.3** |
| Serial configuration | **PASS**, active VT100 getty, **115200**, cs8, -parenb, -cstopb, -crtscts |
| Diskless operation | **PASS**, root tmpfs, boot ISO9660 and modloop SquashFS read-only |
| Remote login service | No listening TCP sockets in the isolated guest; no SSH service enabled |
| UEFI | Boot metadata and EFI payloads preserved; **UEFI execution not tested** |
| RN426 | **Not tested**; QEMU does not reproduce its AMI UART routing, IRQ quirks or USB firmware |

Full readable serial logs and machine-readable test results are in `evidence/qemu-*.log` / `.json`; raw control-character captures are ignored under `artifacts/alpine/qemu-raw`. Initial harness runs exposed duplicate CR characters and an ANSI sequence following ISOLINUX's typed echo. Those matchers were corrected; the final deterministic image passed all three complete tests above. No image workaround or getty overlay was needed for the harness issues. The third test is additional proof of bootloader input and does not replace the independent no-input boot tests.

## Write to expendable USB — operator action only

After identifying the intended **whole expendable USB device**, replace `/dev/sdX` below. This command erases that target. It was **not executed**:

```sh
sudo dd if=/home/user/DEV/tenerix/artifacts/alpine/alpine-3.24.3-rn426-serial-x86_64.iso \
  of=/dev/sdX bs=4M status=progress conv=fsync
```

Use picocom at **115200, 8N1, no flow control**. Boot this medium through the intended Legacy BIOS path; it requires no menu entry or boot-prompt typing. At the ordinary local `login:` prompt, use the official Live account `root` (no password in the untouched Live baseline). No automatic root shell or remote passwordless account was added.

This is a serial-enabled **standard Alpine Live image**, not a storage-isolation appliance. It retains Alpine's existing boot-media discovery and normal startup behavior. No RAID assembly, unlock, format, install or additional mount automation was added. The kernel has MD_AUTODETECT disabled, but that alone is not a guarantee against all userspace discovery or activation on arbitrary attached media. Booting with irreplaceable production HDDs connected was not tested or authorized by this build. Isolate those disks for the first physical experiment; do not treat QEMU success as evidence that production disks remain untouched.
