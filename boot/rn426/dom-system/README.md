# Tenerix Zero — self-contained DOM system (RN426)

A complete Alpine system on the internal 240 MiB USB DOM. No hard disks or pendrive are needed:
the NAS boots from the DOM by itself, gets DHCP and runs sshd.

| Item | Value |
|---|---|
| Image | `artifacts/dom-system/tenerix-rn426-dom-system.img` (outside Git), 251,658,240 bytes |
| Base | verified factory DOM image; MBR, VBR, `ldlinux.*` and trailing sectors byte-identical |
| Loader | factory SYSLINUX 6.03: COM1 115200, 3 s autoboot, `current` / `previous` / `recovery` |
| Kernel | Alpine `6.18.58-0-lts` (same as the Alpine Live hardware test), microcode for the Atom C3538 only |
| Root | `/tenerix/root.img` on the DOM FAT: 150 MiB ext4, loop-mounted read-write, persistent |
| Network | DHCP on eth3, eth0, eth1, eth2 (whichever port has a cable) |
| SSH | root with keys only: three security keys (`artifacts/dom-system/authorized_keys`) |
| Console | root password on ttyS0/tty1: `artifacts/dom-system/root-password` (outside Git) |
| Fans/sensors | exact-ABI `it87.ko` (IT8613E) in `/lib/modules/…/updates/`, loaded at boot with the hardware-test parameters; `coretemp`. The [fan keeper](fan/README.md) sets PWM2 to 80 and switches to full speed on excessive temperatures or invalid CPU/board readings |
| Disks | `mdadm.conf` is `AUTO -all`; nothing is assembled or mounted automatically if disks are inserted |

`build.py` keeps only the kernel modules listed in it, plus their dependencies (USB, SATA,
ixgbe, af_packet, ext4/vfat/loop, md/dm-crypt/btrfs for later use, hwmon). `init` finds the DOM
FAT partition by its MBR PARTUUID `fd8988d9-01`. A second device with a cloned DOM image stops
boot with a duplicate error.

## Build and test (local container)

```sh
cat ~/.ssh/id_ed25519_sk_yubikey{1,2,3}.pub > artifacts/dom-system/authorized_keys
podman exec -w /work/boot/rn426/dom-system tenerix-dom-builder python3 build.py
podman exec -w /work/boot/rn426/dom-system tenerix-dom-builder python3 qemu-test.py
```

`qemu-test.py` boots a writable copy of the exact image in QEMU (legacy BIOS, DOM as USB storage,
four NICs, the fourth with MAC `b0:b9:8a:45:13:fb`). It checks factory SYSLINUX and autoboot,
the loop ext4 root, OpenRC, DHCP on eth3, sshd reachable through eth3, acceptance of the three
ED25519-SK keys, that it87 resolves to `updates/`, password login on ttyS0, persistence across
a reboot, and the `previous` and `recovery` entries on cold boots. QEMU does not prove
compatibility with the real RN426 hardware.

## Write to the DOM (on the NAS, from Alpine Live)

```sh
scp artifacts/dom-system/tenerix-rn426-dom-system.img boot/rn426/dom-system/write-dom.sh root@192.168.1.115:/tmp/
ssh root@192.168.1.115 sh /tmp/write-dom.sh /tmp/tenerix-rn426-dom-system.img <sha256>
```

`write-dom.sh` checks the image hash, finds the DOM only as USB 1-2 `13fe:5200` with 491,520
sectors, prints its current hash, unmounts it, asks for `YES`, writes it with `dd`, then
verifies by read-back. Restoring the factory DOM works the same way, using
`artifacts/dom/readynas-rn426-original-240m.img` and
`40056ae60cf7bbae0b7945797066db7ae7665fb5da1f62e009ae4d0f1355dea7`.

## Limits

* FAT has no journal. The root file has a fixed size, so normal writes only touch its data
  clusters; the ext4 inside has a journal. A power cut can still leave the FAT dirty.
* The DOM is flash memory: avoid heavy write load (logs stay small; there is no swap).
* No automatic updates. `previous` currently boots the same build as `current`.
