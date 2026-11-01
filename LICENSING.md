# Licensing

Original Tenerix code, documentation, and other original contributions are
dedicated under CC0 1.0 Universal, unless a file or directory specifies otherwise.
The full CC0 text is in [LICENSE](LICENSE). This dedication applies only to rights
the contributors hold; it does not relicense third-party material.

## Exceptions and third-party material

| Material | License | Attribution and license text |
|---|---|---|
| `hardware/front-panel/` local integration | MIT | The adapter uses the MIT license in [hardware/front-panel/LICENSE](hardware/front-panel/LICENSE), as documented in its README and source. |
| Panel dependency fetched into `hardware/front-panel/.upstream/` | MIT | `riplatt/truenas-rn426-panel`; pinned revision and file checksums are in [provenance.json](hardware/front-panel/provenance.json). The checkout is not tracked. Its original MIT notice is preserved in `hardware/front-panel/LICENSE`. |
| `hardware/it8613e/upstream/*.c`, `hardware/it8613e/upstream/*.patch`, and `hardware/it8613e/patches/*.patch` | GPL-2.0-or-later | Linux `it87` driver and derived backport. Original authorship notices and upstream patch metadata are preserved. Source revisions and backport origins are recorded in [provenance.json](hardware/it8613e/provenance.json) and the directory README. GPL version 2 is reproduced in [COPYING](hardware/it8613e/COPYING). |
| `boot/rn426/md-system/btrfs-readynas/*.patch` | GPL-2.0-only | Changes to Linux Btrfs `tree-checker.c` and `disk-io.c`, whose upstream SPDX identifier is `GPL-2.0`. Origins and behavior are described in the [directory README](boot/rn426/md-system/btrfs-readynas/README.md). The GPL version 2 text is in [hardware/it8613e/COPYING](hardware/it8613e/COPYING). |

The surrounding original build tools and documentation retain the default CC0
dedication unless explicitly covered by an exception above. License texts,
upstream authorship notices, and any third-party excerpts in documentation or
evidence retain their original terms. Their presence does not place them under
CC0. Preserve applicable notices when redistributing those materials.

## Generated systems and deployment bundles

Build scripts do not change the licenses of the software they package. Generated
systems and bundles can include Linux, Alpine packages, panel code, firmware, and
other components under their respective terms; they are not covered as a whole
by the repository's default CC0 dedication.

When distributing binaries, satisfy the license requirements of each included
component, including applicable corresponding-source obligations for GPL
components. A license text, checksum, or upstream URL alone does not establish
that these obligations have been met.
