# Tenerix Zero — RN426 DOM boot prototype

This is the first persistent boot prototype for Tenerix Zero on the NETGEAR ReadyNAS RN426:

```
internal 240 MiB USB DOM (factory SYSLINUX 6.03, FAT16)
  └─ kernel + initramfs (Alpine linux-lts 6.18.58-0-lts), two slots + RAM recovery
       └─ system MD RAID1 (six members, metadata 1.2, explicit UUID) → ext4 Alpine root
            production RAID5 / RAID10 swap: never assembled automatically
```

**Status: QEMU-tested prototype only.** Nothing here has been written to the physical DOM, the
NAS or its disks. QEMU success does not prove compatibility with the real RN426 BIOS or
hardware (see [Before a real RN426 boot](#before-a-real-rn426-boot)).

## Files

| File | Purpose |
|---|---|
| `read-dom.py` | Read-only helper streamed to the NAS over SSH. It checks the DOM's USB topology `1-2`, `13fe:5200`, 491,520 × 512 B, the single MBR partition 32+458,720 and the read-only vfat mount, then hashes or streams the device with `O_RDONLY`. It never creates a remote file. |
| `acquire-dom.py` | Local side of the acquisition. It hashes the source before and after the transfer, writes the image with `O_EXCL` (never overwrites a backup), checks length and SHA-256, and sets the image read-only. |
| `Containerfile` | Pinned local toolbox (`localhost/tenerix-dom-tools:3.24.3`): QEMU 11.0.3, SeaBIOS 1.17.0, mtools, mkinitfs, mdadm, pexpect. |
| `packages.txt` | Minimal pinned Alpine 3.24 runtime manifest. The kernel is the retained, signature-verified `linux-lts-6.18.58-r0.apk`. |
| `runtime-resolved.txt`, `tool-packages.txt` | Resolved package versions of the built rootfs and of the toolbox used for the tests. |
| `build-root.sh` | Builds the Alpine root with `apk --no-scripts`: OpenRC runlevels, sshd (keys only), DHCP on `eth3`, front panel, exact-ABI `it87.ko`, depmod. |
| `build.py` | `image`: rootfs, fixture input, slots g0/g1, `rescue`, and the Tenerix DOM image derived from the verified original. `generation ID`: builds a new update generation. |
| `domlib.py` | Image-file-only FAT helpers. It refuses anything that is not a regular 251,658,240-byte file below `artifacts/dom`. |
| `syslinux.cfg.in` | Bootloader template. `SYSLINUX.CFG` is rendered from each slot's `generation.json`. |
| `init` | Disk-boot initramfs `/init`. |
| `recovery-init` | RAM-only recovery initramfs: no arrays, no mounts. |
| `fixture-init` | QEMU-only fixture creator. It never goes into the DOM. |
| `dom-update.py` | `install` / `rollback` / `status` for the two slots of a DOM image file. |
| `qemu.py` | Interactive BIOS/serial QEMU tests. |
| `test-suite.py` | The complete test sequence. |
| `decoy-hashes.py` | Proves that the synthetic swap and data decoy partitions are unchanged. |

Local artifacts, outside Git (`artifacts/dom/`, ignored):

| Path | Content |
|---|---|
| `readynas-rn426-original-240m.img` (+ `.sha256`, `acquisition.json`) | Verified factory DOM. Mode 0400, never modified. This is the factory recovery source. |
| `tenerix-rn426-alpine-boot.img` | Modified Tenerix DOM image. |
| `build/` | rootfs, `rootfs.tar.gz`, slots, rescue, initramfs listings, `runtime-resolved.txt` |
| `system-member-{1..6}.raw` | Disposable sparse fixture disks |
| `generations/proto-c/` | Update test generation |
| `test-images/*.img` | Broken, updated and rolled-back DOM copies |
| `logs/` | Build logs, serial logs per test, `*.json` results, `summary.json` with SHA-256 manifest |

## Reproduce

```sh
podman build -t localhost/tenerix-dom-tools:3.24.3 boot/rn426
podman run -d --name tenerix-dom-builder --network=host \
  -v "$PWD":/work:rw -w /work localhost/tenerix-dom-tools:3.24.3 sleep infinity
python3 boot/rn426/acquire-dom.py                     # once, read-only SSH to the NAS
podman exec -w /work/boot/rn426 tenerix-dom-builder python3 build.py image [--replace]
podman exec -w /work/boot/rn426 tenerix-dom-builder python3 test-suite.py
```

The rootfs is downloaded from the pinned Alpine v3.24 repositories (network only during
`build-root.sh`). The kernel APK is the one retained by the hardware test
(`artifacts/alpine-hardware/packages/`). `build.py` refuses to run unless the original image
hash is `40056ae6…dea7`.

## Phase 1 — factory DOM acquisition

| Item | Value |
|---|---|
| Device | USB `1-2`, `13fe:5200`, then `/dev/sdg` (rediscovered, not assumed) |
| Size | 251,658,240 bytes = 491,520 × 512 B |
| Partition | MBR #1, active, type 06 (FAT16), start 32, 458,720 sectors |
| Mount | `/mnt/internal` `ro,nosuid,nodev,noexec,noatime`, unchanged |
| SHA-256 | `40056ae60cf7bbae0b7945797066db7ae7665fb5da1f62e009ae4d0f1355dea7` (source before = after = local) |
| MBR SHA-256 | `80ed3e8598aeca576ccf5fe62ed27f112fe8a31ad1fd1b143ab015bfeb192e52` |

## Phase 2 — bootloader analysis

* The MBR boot code, VBR and `ldlinux.sys` / `ldlinux.c32` are SYSLINUX **6.03** (2018 build).
  There are no COM32 modules besides `ldlinux.c32` (no `menu.c32` or `chain.c32`), so only the
  built-in command-line `boot:` prompt is available. That is enough for a serial selection.
* FAT16 layout: 512-byte sectors, 4 KiB clusters, two FATs of 224 sectors, 458,720 sectors
  (≈ 224 MiB). The last 16 MiB of the device (sectors 458,752–491,519) are outside the partition.
* The factory `SYSLINUX.CFG` has `serial 0 115200`, `timeout 30`, `prompt 0`,
  `default Normal`, `onerror Rescue`. Its labels pass `reason=normal|factory|os_reinstall|diag|
  vol_ro|test_disks|rescue` to the vendor initramfs. `FactoryDefault`, `OSReinstall` and
  `TestDisks` are destructive vendor procedures.
* The factory loader boots unmodified Alpine `vmlinuz-6.18.58-0-lts` (14.6 MB bzImage, boot
  protocol 2.15) with a list of two initrds (microcode cpio + initramfs). Measured in QEMU:
  no loader replacement or repair is needed. Only the configuration and payload files change.
* Practical size limit: about 90 MB per generation, given g0 + g1 + rescue and the 32 MiB
  margin (see Phase 6). The kernel's `initrd_addr_max` is 0x7fffffff, so SYSLINUX places no
  relevant limit on a 6 MB initramfs.

## Phase 3 — Tenerix DOM image

`build.py image` copies the verified original and changes only files inside the FAT:

* It deletes `KERNEL`, `INITRD.GZ`, `KERNEL.EMG`, `INITRD.EMG`, `ROOT.TLZ`, `CSUMS.MD5` and the
  factory `SYSLINUX.CFG`, so no entry can reach vendor factory-reset, reinstall or disk-test code.
* It adds `g0/`, `g1/`, `rescue/` and a new `SYSLINUX.CFG`.
* It asserts that MBR + gap + VBR (first 16,896 bytes), `ldlinux.sys`, `ldlinux.c32`, the
  trailing 16 MiB and the device size are byte-identical to the original.

Boot configuration (rendered):

```
SERIAL 0 115200 0        COM1 115200 8N1 bootloader I/O, VGA kept (CONSOLE 1)
PROMPT 1 / TIMEOUT 30    serial boot: prompt, automatic boot after 3 s
DEFAULT/ONTIMEOUT current
ONERROR previous         a missing/unloadable current kernel falls back automatically
LABEL current            /gN/vmlinuz-6.18.58-0-lts + ucode-20260812.cpio,initramfs-6.18.58-0-lts
LABEL previous           the other slot
LABEL recovery           /rescue: RAM-only shell, no storage activation
APPEND console=tty0 console=ttyS0,115200n8 panic=0 raid=noautodetect tenerix.slot=gN
```

Each slot holds explicitly versioned files plus `generation.json` (build ID, kernel release,
file names) and `SHA256SUMS`. The kernel release is read from the bzImage header and must match
the `lib/modules/<release>` tree of the same rootfs. 6.18.59 inputs are never mixed in.

## Phase 4 — persistent root and early boot

Runtime: Alpine 3.24.3 + OpenRC 0.63.2, openssh 10.3p1, mdadm 4.3, cryptsetup 2.8.6,
btrfs-progs 6.17.1, nfs-utils 2.6.4, smartmontools, intel-ucode 20260812, Python 3.14 + Pillow
for the front panel, and the exact-ABI IT8613E `it87.ko` for 6.18.58-0-lts. 123 packages in
total (`build/runtime-resolved.txt`), with no Docker, web UI or NAS distribution. The kernel
package is installed without scripts, so no host or rootfs initramfs hook runs.

Enabled services: `devfs sysfs dmesg` (sysinit), `root hostname bootmisc sysctl modules syslog`
(boot), `networking sshd` (default). `mdadm`, `mdadm-raid`, `localmount`, `swap`, `nfs`,
`dmcrypt` and the hotplug/mdev helpers are **not** enabled. `/etc/mdadm.conf` is `AUTO -all`.
The front panel and `it87.ko` are installed in `/opt/tenerix`, but they are **not started
automatically**. They change fan/OLED state, so enabling them is a separate step that needs
hardware authorization.

`init` (the initramfs) contains no `nlplug-findfs`, does no `mdadm --scan`/`--incremental` and
does no key discovery:

1. It loads only `ahci sd_mod usb_storage uas xhci_pci virtio_pci virtio_blk raid1 ext4`.
   There is no raid456 or raid10 personality and no dm-crypt in the initramfs.
2. It finds the system members by the six embedded GPT **PARTUUIDs** (kernel uevent data,
   partition number 1 only), with 60 s to find at least 5 of 6.
3. `mdadm --examine` must report the explicit `SYSTEM_MD_UUID` and level raid1 for every member.
4. `mdadm --assemble /dev/md0 --uuid=… --run <members>`, then it checks level raid1, metadata
   1.2 and the root filesystem UUID before mounting.
5. It mounts ext4 `rw,noatime`, checks the marker file `/etc/tenerix/root-fs-uuid`, writes
   `/run/tenerix-generation` (slot from the command line) and `/run/tenerix-build` (build ID),
   then runs `switch_root` to `/sbin/init`.
6. On any failure it prints `TENERIX_RECOVERY:` and opens a serial shell. Nothing else is
   activated.

Networking: `eth3`, DHCP only, guarded by `pre-up` so that it only comes up when the MAC matches.
The prototype rootfs pins the QEMU test MAC `52:54:00:42:60:04`. The production rootfs must
use `b0:b9:8a:45:13:fb` (`build/network-mac`). No static address: `192.168.1.115` is only the
address DHCP handed out before.

## Phase 5 — disposable QEMU tests

The fixture is six sparse 4,563,402,752-byte disks with GPT p1 4 GiB (system RAID1, 8,388,608
sectors like production), p2 swap decoy (RAID10) and p3 data decoy (RAID5), all metadata 1.2.
The UUIDs are new, derived with uuid5 from a project namespace:

| Array | Disposable UUID |
|---|---|
| system RAID1 (md0) | `658a0849:7a9b59d8:a644750a:4f2d9d93` |
| swap decoy RAID10 | `16b5a5c9:758f5898:9e840ced:2d01ac9a` |
| data decoy RAID5 | `10c8ddfa:6c0c563a:a97b1244:bc0af205` |
| root ext4 | `1bbb3c7d-7cd5-571a-8248-bc87fde39918` |

None of these is a production UUID (production md0 is `58b7f1b0:…`). The fixture partitions
start at sector 2048; production p1 starts at 64. The member size is the same.

QEMU: `pc` machine, SeaBIOS legacy BIOS, TCG, the DOM image as **read-only** USB mass storage
on xHCI (`bootindex=1`), six virtio disks, four e1000 NICs (the fourth is `eth3`, user-mode
network `restrict=on`, SSH forwarded to 127.0.0.1), `-display none -serial stdio`. Every test
drives the real serial console with pexpect: the `boot:` prompt, `root` login on `ttyS0`, a
shell probe, SSH with the test key, then poweroff.

Results of the last full `test-suite.py` run (`TEST_SUITE_PASSED`; logs in
`artifacts/dom/logs/<name>.log|json`, combined in `summary.json`):

| Test | DOM image | Input at `boot:` | Booted slot / build | Login (s) | Result |
|---|---|---|---|---:|---|
| `current` | Tenerix | none (3 s timeout) | g1 / proto-b | 24.8 | pass: RAID1 6/6 root, OpenRC, DHCP, SSH, clean `reboot`, random nonce persisted |
| `previous` | Tenerix | `previous` | g0 / proto-a | 20.2 | pass |
| `recovery` | Tenerix | `recovery` | RAM shell | – | pass: serial input works, no md, no disk mounts |
| `broken-kernel` | g1 kernel deleted | none | g0 / proto-a | 23.9 | pass: `Loading /g1/… failed: No such file` → `ONERROR previous`, unattended |
| `broken-initramfs` | g1 initramfs truncated to 1/3 | none, then power cycle + `previous` | g0 / proto-a | 33.0 | pass: first boot stopped in `TENERIX_RECOVERY: required module failed: ahci`, nothing assembled; recovered over UART |
| `updated-current` | after `dom-update.py install proto-c` | none | g0 / proto-c | 22.7 | pass |
| `updated-previous` | same | `previous` | g1 / proto-b | 16.6 | pass |
| `rolled-back` | after `dom-update.py rollback` | none | g1 / proto-b | 21.5 | pass |
| `degraded` | Tenerix, 5 of 6 disks | none | g1 / proto-b | 19.8 | pass: md0 `[6/5]` |

The probe in every boot test checks all of the following: the root is `/dev/md0` ext4 rw;
`uname -r` = `6.18.58-0-lts`; the slot/build markers; only `md0` is active, never the RAID10
swap decoy or the RAID5 data decoy; `/proc/swaps` is empty; `rc-status` shows `sshd` started;
`eth3` has a DHCP address; and SSH login with the test key returns the same build ID. The SHA-256
of the synthetic decoy partitions is identical before and after the whole suite. From the
`boot:` prompt to `Linux version` takes about 4.6–4.9 s under TCG (3 s timeout + kernel load).

SHA-256 of the images in this run:

| Image | SHA-256 |
|---|---|
| `readynas-rn426-original-240m.img` | `40056ae60cf7bbae0b7945797066db7ae7665fb5da1f62e009ae4d0f1355dea7` |
| `tenerix-rn426-alpine-boot.img` | `c1b070101df5c36d189bc06510e7d1a1507d6bc18bf8b534b97766e852fae764` |

The FAT keeps timestamps from the build time, so a rebuild gives a different image hash. The
slot payloads are verified by their `SHA256SUMS`.

## Phase 6 — capacity and updates

Measured on `tenerix-rn426-alpine-boot.img`:

| Item | Bytes |
|---|---:|
| FAT16 partition | 234,864,640 |
| `ldlinux.sys` + `ldlinux.c32` + `SYSLINUX.CFG` | 181,893 |
| slot g0 (kernel 14,603,264 + microcode 15,265,040 + initramfs 5 985 723 + metadata) | 35,854,551 |
| slot g1 | 35,854,546 |
| `rescue` (kernel + recovery initramfs + metadata) | 20,586,361 |
| **free** | **142,077,952** |

The factory layout had 133,095,424 bytes free. An update reuses the inactive slot, so it never
needs a third slot. The measured install of a 35,854,762-byte generation left 142,077,741 bytes
free. With the 32 MiB margin, two equal generations can each be up to about **90 MB**, about
2.5 × the current size. The generic `intel-ucode` archive (15.3 MB, all Intel CPUs) is the
largest saving left: a cpio with only the Atom C3538 (06-5f-01) blob would cut each slot by
about 15 MB. It is not done here because the content must first be verified.

### Update mechanism (`dom-update.py`)

1. `build.py generation ID` builds kernel, microcode and initramfs from **one** rootfs, so
   modules and kernel always match, and writes `generation.json` + `SHA256SUMS`. Generations
   are immutable once built.
2. `dom-update.py install IMAGE DIR`
   * checks the local hashes, refuses a build ID that is already installed, and computes the
     space (`free + reclaimed − incoming ≥ 32 MiB`, otherwise nothing changes);
   * clears and writes **only the inactive slot**. The active slot, and therefore a bootable
     kernel, is never touched;
   * reads every staged file back through the FAT layer and compares it with `SHA256SUMS`;
   * stages `SYSLINUX.NEW`, verifies it, then replaces `SYSLINUX.CFG` (new = current, old
     current = previous).
3. `dom-update.py rollback IMAGE` swaps current and previous. It only changes the configuration.
4. The previous slot can be selected at any time by typing `previous` at the serial `boot:`
   prompt.

No unattended updates and no automatic kernel switching ("try once, then fall back"). That
needs a persistent counter (for example SYSLINUX ADV), whose behaviour on this appliance has
not been validated. This prototype only operates on image files. Applying it to a real DOM
needs a separately reviewed tool for a mounted vfat partition.

### Kernel rollback vs. OS rollback

The two slots roll back **kernel + initramfs + module ABI pinning** only. The root filesystem
on md0 is shared by both slots: packages, configuration and `/lib/modules` are not rolled back.
A slot is only bootable if its kernel release has a module tree in the current root. Therefore
a kernel update must add the new `/lib/modules/<release>` to the root **without removing the
previous release** until the previous slot is retired. Full OS rollback needs a separate root
snapshot or backup of md0 (for example an ext4 image or a second root LV). That is outside
this prototype.

### FAT power-loss limitations

FAT16 has no journal. A power loss during an update can leave lost clusters, a truncated file
or a missing directory entry. The design limits the damage:

* The active slot's files are never rewritten, so their data clusters stay intact.
* Only one step changes what boots: deleting `SYSLINUX.CFG` and renaming `SYSLINUX.NEW` to it.
  If power fails between the two, SYSLINUX finds no configuration and stops at `boot:`
  **without** autobooting. An operator on UART can still type
  `/g1/vmlinuz-6.18.58-0-lts initrd=… tenerix.slot=g1 console=ttyS0,115200n8` by hand.
* Both FAT copies are updated by the filesystem driver, not atomically. An interrupted FAT
  update can affect any file, including `ldlinux.sys`. The protection against this is the
  **separate recovery image**: the verified factory image and the current Tenerix DOM image,
  kept off-device and restorable over a clean 240 MiB write.
* `ldlinux.sys` and the boot sectors are never rewritten by updates.

## Safety summary

* SSH to the NAS was only used for read-only identification, hashing and streaming of the DOM.
  Nothing was created on the NAS, and nothing was mounted, assembled, unlocked or rebooted.
* All image modifications, installations and boots ran locally on cloned images and disposable
  sparse disks inside a container. QEMU opens the DOM image read-only.
* No raw images, keys or credentials are committed. The test SSH key and the empty console
  root password exist only in the disposable test rootfs.

## Before a real RN426 boot

1. Production rootfs build: the real `SYSTEM_MD_UUID`, PARTUUIDs and root filesystem UUID; the
   MAC `b0:b9:8a:45:13:fb`; a real authorized key; a root password or locked console instead of
   an empty one; and no test key.
2. Migration decision for md0: the factory system root is **Btrfs** on md0. Making it the
   ext4 Alpine root destroys the factory OS root, which the DOM backup does **not** contain.
   That needs a full backup of md0 (and a plan for factory restore) first.
3. Test on disposable hardware (a spare DOM-sized USB stick or a clone of the DOM, spare disks)
   before touching the internal DOM: real AMI BIOS USB boot, SYSLINUX timing and serial on
   the real UART, real `ahci`/`ixgbe` ordering (is `eth3` still the RJ45 with that MAC?),
   reset button and IT8613E behaviour.
4. Decide and enable the front-panel and fan services under supervision. The hardware test
   procedure is in `hardware/alpine-hardware-test/README.md`.
5. A vfat-mounted variant of `dom-update.py`, reviewed separately, plus a restore procedure
   for the DOM from the off-device images.
6. Each step on the NAS needs its own authorization. This repository authorizes none of them.
