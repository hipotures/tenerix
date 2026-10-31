# Build only: no install, load, signing, depmod, or initramfs targets.
KVER := 6.12.107+deb13-amd64
KDIR ?= /lib/modules/$(KVER)/build
BUILD := $(CURDIR)/build
export KBUILD_BUILD_USER := rn426-audit
export KBUILD_BUILD_HOST := reproducible
export KBUILD_BUILD_TIMESTAMP := 2026-10-31 00:00:00 UTC
export KBUILD_BUILD_VERSION := 1
export SOURCE_DATE_EPOCH := 1793404800

.PHONY: all check
all: check build/it87.c build/Kbuild
	$(MAKE) -C "$(KDIR)" M="$(BUILD)" -j2 W=1 KCFLAGS="-ffile-prefix-map=$(CURDIR)=/usr/src/rn426-it8613e" modules

check:
	@test "$$(uname -r)" = "$(KVER)" || { echo 'Wrong running kernel ABI' >&2; exit 1; }
	@test "$$(cat "$(KDIR)/include/config/kernel.release")" = "$(KVER)" || { echo 'Wrong header ABI' >&2; exit 1; }
	@test -s "$(KDIR)/Module.symvers"
	sha256sum --check SOURCES.sha256

build/it87.c: upstream/linux-6.12.107-it87.c patches/0001-backport-it8613e-linux-6.12.107.patch
	mkdir -p build
	cp -- upstream/linux-6.12.107-it87.c build/it87.c
	patch --batch --fuzz=0 --no-backup-if-mismatch -d build -p1 < patches/0001-backport-it8613e-linux-6.12.107.patch

build/Kbuild: Kbuild
	mkdir -p build
	cp -- Kbuild build/Kbuild
