# ReadyNAS root flag 0x10000 on the data volume

ReadyNAS OS 6 sets bit 16 (`0x10000`) in the `ROOT_ITEM` flags of the affected share subvolume
(root 9054). Stock Linux 6.18 rejects it in `tree-checker.c` ("invalid root flags"), so that
subvolume returns I/O errors. Both DUP metadata copies carry the same value. All other
subvolumes have flags `0x0`.

* `tenerix-readynas-tolerate.patch`: the tree checker accepts bit 16 and changes nothing else.
  Built out of tree against Alpine linux-lts 6.18.59 (vanilla btrfs: Alpine has no btrfs
  patches). It is loaded by hand with `insmod` instead of the stock btrfs module. Used
  read-only: the affected share mounts and reads.
* `tenerix-readynas-root-flag.patch`: additionally clears the bit in memory when a root is
  loaded, so it is written out on the next update of that subvolume. **Not used.** Whether to
  clear the bit on disk remains a separate operational decision. Its auto-defragmentation
  meaning is established by the source analysis below.

## Meaning of the flag (from NETGEAR's GPL source)

Source: [ReadyNASOS_V6.10.6_WW_src.zip](https://archive.org/download/netgearfirmwaresgpl/ReadyNASOS_V6.10.6_WW_src.zip),
preserved in the Internet Archive [netgearfirmwaresgpl collection](https://archive.org/details/netgearfirmwaresgpl).
The analysis used the `linux-4.4.218-x86_64` tree, the same kernel line as the RN426
firmware 6.10.10 (4.4.218.x86_64.1), rather than an assertion that the two firmware
versions have identical source.

NETGEAR's [official GPL source catalog](https://www.downloads.netgear.com/files/GDC/2649_GPLv1.html)
still lists ReadyNAS OS 6.10.6. Its original ZIP download returned HTTP 404 when checked
on 2026-11-01; the archive mirror served a byte-range request successfully. This
repository links to the source archive without redistributing it or applying CC0
to its contents. Individual components retain their original licenses.

* `include/uapi/linux/btrfs.h`: `#define BTRFS_SUBVOL_AUTO_DEFRAG (1ULL << 16)`.
* `fs/btrfs/ioctl.c`: `BTRFS_IOC_SUBVOL_SETFLAGS` / `GETFLAGS` copy this bit straight into and out
  of `root_item.flags`. The firmware binary confirms it: `btrfs_ioctl_subvol_setflags` does
  `or $0x10000`, and `getflags` does `and $0x10000` (disassembly of the DOM `KERNEL`).
* `fs/btrfs/file.c` `__need_auto_defrag()`: the only consumer. If the bit is set, writes to that
  subvolume queue inodes for background auto-defragmentation.

So `0x10000` is a per-share "auto-defrag" switch. It has no on-disk structural meaning.
Clearing it only stops ReadyNAS-style automatic defragmentation of that share; mainline offers
the same behaviour filesystem-wide with `-o autodefrag`. After clearing, the stock Alpine kernel
reads the volume without any patch.

## License and source attribution

Both patches are licensed under GPL-2.0-only, matching the upstream Linux Btrfs
files they modify. `tree-checker.c` carries a copyright notice for Qu Wenruo
(2017); `disk-io.c` carries a copyright notice for Oracle (2007). Existing upstream
notices remain applicable. The local functional changes are dated 2026-10-31 in
the patch headers.

Upstream source references:
[tree-checker.c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/fs/btrfs/tree-checker.c?h=v6.18)
and [disk-io.c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/fs/btrfs/disk-io.c?h=v6.18).
The full GPL version 2 text is provided in
[COPYING](../../../../hardware/it8613e/COPYING). See the repository
[licensing scope](../../../../LICENSING.md) for other components.
