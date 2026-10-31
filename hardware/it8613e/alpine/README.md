# Alpine IT8613E build and deployment artifact

**Actually built and loaded:** Alpine **6.18.58-0-lts**, x86_64. This is not a
6.18.59 module or the earlier Debian binary. Complete hardware results, including
separately authorized PWM testing, are in the [hardware test](../../alpine-hardware-test/README.md).

## Authenticated inputs

The official current CDN returned 404 for the exact old development package.
The retained HTTPS Alpine mirror at
`https://mirrors.huaweicloud.com/repository/alpine/v3.24/main/x86_64/`
provided both `linux-lts-dev-6.18.58-r0.apk` and `linux-lts-6.18.58-r0.apk`.
**Both passed `apk verify` using the official digest-pinned Alpine base image's
keyring, without allow-untrusted or added signing keys.** Checksums are in
[compatibility.json](compatibility.json) and the hardware evidence. The dev
package's signed `.PKGINFO` identifies aports commit
`5fe63f789de75f6a71001cf2de771f922bedd0d2`.

The package supplies complete prepared headers, generated includes, build tools,
GCC plugin and `Module.symvers`; no `modules_prepare` substitute or fabricated
symbol table is used. Header config SHA-256 is
`24cbcda9272285a9e10a09d19a971715a15c17c242757e8729f0f28bac7eac71`.
The sole difference from the original Live configuration is compiler name
`gcc` versus `cc` in `CONFIG_CC_VERSION_TEXT`; both are Alpine GCC 15.2.0.
The stock module extracted from the signed kernel APK, after gzip decompression,
is byte-identical to the running Live stock it87:
`08054442cb091d113e7466e237ddfb5e07a8f291f5d9ae15bd733c849e700cf7`.

The exact Linux 6.18.58 baseline driver is byte-identical to the committed
6.12.107 baseline. Reuse the existing consolidated zero-fuzz backport of the
three commits in `../provenance.json`; **no new driver, register changes or kernel
API adaptations** were introduced. The consolidated patch intentionally omits
unrelated IT8689 support, as documented in the original investigation.

## Rebuild on the development machine

Run from the repository root. These commands never contact the NAS:

```sh
python3 hardware/it8613e/alpine/fetch-inputs.py
podman build --network=none --pull=never \
  -f hardware/it8613e/alpine/Containerfile \
  -t localhost/tenerix-it8613e-alpine:6.18.58 artifacts/alpine-hardware
podman run --rm --network=none --pull=never \
  -v "$PWD:/work:rw" localhost/tenerix-it8613e-alpine:6.18.58 \
  sh hardware/it8613e/alpine/build.sh /work/artifacts/alpine-hardware/fresh-build
```

Use a fresh output directory. The fetcher verifies committed hashes for every
retained APK; the offline Containerfile then verifies Alpine signatures before
installing the exact closure. It fails if an input is missing or has changed.
If old dependency archives disappear from mirrors, reuse the retained local
archives; never silently change versions. The base image is pinned by digest.
`builder-apks.sha256` pins the full build/test closure;
`builder-packages.txt` records the initial compiler/header installation. The
closure also includes Pillow/font packages used for Alpine software testing.
No kernel image is installed inside the builder; the kernel APK is unpacked only
for file validation. Its package hooks are never run there.

Build-only dependencies include GCC **15.2.0-r5**, binutils **2.45.1-r1**, Make,
libc-dev, patch, Perl, gmp/mpc/mpfr development libraries, elfutils-dev, bash,
flex, bison and zstd. Python and kmod provide verification. None of this
compiler/header toolchain was installed on the NAS.

Build uses `W=1`, `-Werror`, unchanged kernel instrumentation and normalized debug
paths. Alpine enables the GCC latent-entropy plugin: the first unseeded pair
was not reproducible. The plugin explicitly supports GCC `-frandom-seed`; fixing
it to `rn426-it8613e-6.18.58` produces identical bytes across two fresh directories
and a third build in the independently reconstructed offline image. The plugin
was not disabled. Fixed build identity/time are recorded in `build.sh`.

BTF is skipped by stock kbuild because the development APK omits `vmlinux`.
`CONFIG_DEBUG_INFO_BTF` was not disabled, and no build warning was suppressed.
This does not prevent the verified module load; BPF module-type introspection
is not supplied by this artifact.

## File validation and reproducibility

After extracting the authenticated kernel package with a tar implementation
that handles concatenated APK streams (GNU tar `--ignore-zeros`):

```sh
python3 hardware/it8613e/validate.py artifacts/alpine-hardware/fresh-build/it87.ko \
  --kernel 6.18.58-0-lts --headers /usr/src/linux-headers-6.18.58-0-lts \
  --stock artifacts/alpine-hardware/kernel-package/lib/modules/6.18.58-0-lts/kernel/drivers/hwmon/it87.ko.gz
```

Run this in the Alpine builder with repository paths under `/work`. The validator
is file-only and accepts an explicit target ABI rather than requiring the build
host to run that kernel. Existing Debian invocation defaults remain unchanged.
It verifies ELF64 little-endian x86-64 relocatable format, GPL/name/vermagic,
all **42 strong imports**, and **43 embedded version CRCs**, including
`module_layout`, against the exact symbol table. Providers: vmlinux, hwmon and
hwmon-vid. Deliberate CRC corruption is rejected. No force-load is used.

Final module:

- `artifacts/alpine-hardware/repro-one/it87.ko`, **945688 bytes**.
- SHA-256: **`1155aae1cb9e794f41a719dc34ffe8df4a950c0911bc3b9d97cc4d5990235cf9`**.
- Vermagic: **`6.18.58-0-lts SMP preempt mod_unload modversions`**.
- Dependencies: matching **hwmon, hwmon-vid**.
- GPL, unsigned, no external proprietary code.

## Version-pinned deployment bundle

```sh
python3 hardware/it8613e/alpine/package-bundle.py
```

Creates ignored local `artifacts/alpine-hardware/tenerix-rn426-6.18.58-0-lts.tar.gz`
and `.sha256`. It contains the checksum-verified module, exact compatibility
manifest, existing panel adapter, six pinned upstream runtime files, MIT/GPL
licenses and per-file hashes. It contains **no installer, automatic load,
service, depmod or initramfs hook**. Two invocations produce identical bytes.
This is the equivalent pinned deployment artifact requested for this phase;
no custom APK signing key is embedded or generated.

A future signed Alpine module package must depend on exactly
`linux-lts=6.18.58-r0`, install its module under that release's `extra/` directory,
and resolve the stock `it87` name deliberately. Ordinary `modprobe it87` currently
still selects stock. Do not install both as independent drivers or force a
module built for another release. Package/depmod/autoload integration requires
separate deployment authorization and testing. This task did not install it.

For every future kernel update, archive its signed kernel/dev APK pair, config,
symbol table and toolchain, rebuild the same reviewed source, repeat CRC and
reproduction checks, then supervise a detection-only hardware test first.
Builds for **6.18.59-0-lts are not supplied**. A transition must deploy its matching
kernel, modules and initramfs as a separate recoverable boot generation, without
rewriting the only working boot assets or blindly enabling data RAID assembly.
A kernel rollback does not undo hardware registers or filesystem transactions.
