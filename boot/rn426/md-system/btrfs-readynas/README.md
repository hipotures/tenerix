# ReadyNAS root flag 0x10000 on the data volume

ReadyNAS OS 6 sets bit 16 (`0x10000`) in the `ROOT_ITEM` flags of the share subvolume `Archiwum`
(root 9054). Stock Linux 6.18 rejects it in `tree-checker.c` ("invalid root flags"), so that
subvolume returns I/O errors. Both DUP metadata copies carry the same value. All other
subvolumes have flags `0x0`.

* `tenerix-readynas-tolerate.patch`: the tree checker accepts bit 16 and changes nothing else.
  Built out of tree against Alpine linux-lts 6.18.59 (vanilla btrfs: Alpine has no btrfs
  patches). It is loaded by hand with `insmod` instead of the stock btrfs module. Used
  read-only: `Archiwum` mounts and reads.
* `tenerix-readynas-root-flag.patch`: additionally clears the bit in memory when a root is
  loaded, so it is written out on the next update of that subvolume. **Not used.** Whether to
  clear the bit on disk is still open: its exact NETGEAR meaning (snapshot related) is unknown.
