#!/usr/bin/env python3
"""Repack the checksum-pinned official ISO; only two boot configs change."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts/alpine"
SOURCE_NAME = "alpine-standard-3.24.3-x86_64.iso"
OUTPUT_NAME = "alpine-3.24.3-rn426-serial-x86_64.iso"
BASE_URL = "https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/"
SOURCE_SHA = "1629ffe7308d4f3d3eeeed3a97d09ad62293f6d37ef3e483a7306077fdac12be"
BIOS_CFG = "boot/syslinux/syslinux.cfg"
EFI_CFG = "boot/grub/grub.cfg"
CONSOLES = "console=tty0 console=ttyS0,115200n8"
STAMP = "2026102100000000"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(args, log):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log.write_text("$ " + " ".join(str(a) for a in args) + "\n" + result.stdout)
    result.check_returncode()
    return result.stdout


def source():
    directory = ARTIFACTS / "original"
    directory.mkdir(parents=True, exist_ok=True)
    for name in (SOURCE_NAME + ".sha256", SOURCE_NAME):
        path = directory / name
        if not path.exists():
            partial = path.with_name(name + ".part")
            print(f"Downloading {BASE_URL + name}", flush=True)
            with urllib.request.urlopen(BASE_URL + name, timeout=60) as response, partial.open("wb") as target:
                while block := response.read(1024 * 1024):
                    target.write(block)
            partial.rename(path)
    published = (directory / (SOURCE_NAME + ".sha256")).read_text().split()
    if published != [SOURCE_SHA, SOURCE_NAME]:
        raise RuntimeError("Published checksum does not match the reviewed release pin")
    original = directory / SOURCE_NAME
    if sha(original) != SOURCE_SHA:
        raise RuntimeError("Original ISO checksum mismatch; refusing to modify it")
    print(f"Verified original SHA-256 {SOURCE_SHA}", flush=True)
    return original


def modify_bios(original):
    default = re.search(r"^DEFAULT\s+(\S+)\s*$", original, re.M).group(1)
    if re.findall(r"^LABEL\s+(\S+)", original, re.M) != [default]:
        raise RuntimeError("Unexpected BIOS labels; review source ISO layout")
    body = original[original.index("LABEL "):]
    def append(match):
        args = match.group(1).split()
        if any(a.startswith("console=") for a in args):
            raise RuntimeError("Unexpected pre-existing console options")
        args = [a for a in args if a != "quiet"]
        return "APPEND " + " ".join(args) + " " + CONSOLES
    body, count = re.subn(r"^APPEND[ \t]+([^\r\n]*)", append, body, flags=re.M)
    if count != 1:
        raise RuntimeError("Expected one BIOS kernel command line")
    return ("SERIAL 0 115200 0\nCONSOLE 1\nNOHALT 1\n"
            "TIMEOUT 30\nTOTALTIMEOUT 30\nPROMPT 1\n"
            f"DEFAULT {default}\nONTIMEOUT {default}\n\n" + body)


def modify_efi(original):
    if original.count("menuentry ") != 1:
        raise RuntimeError("Unexpected GRUB menu layout")
    result = original.replace("set timeout=1", "set timeout=3\nset default=0", 1)
    def linux(match):
        args = [a for a in match.group(1).split() if a != "quiet"]
        return "linux\t" + " ".join(args) + " " + CONSOLES
    result, count = re.subn(r"^linux[ \t]+([^\r\n]*)", linux, result, flags=re.M)
    if count != 1:
        raise RuntimeError("Expected one GRUB kernel command line")
    # Do not require EFI bootloader serial modules absent from the official image.
    # Its Linux entry gets the same console/getty arguments; BIOS is primary.
    return result


def metadata(iso, prefix):
    return run(["xorriso", "-indev", str(iso), "-report_el_torito", "plain",
                "-report_system_area", "plain"], prefix.with_suffix(".boot.txt"))


def build(original, output):
    if output.exists() or not output.resolve().is_relative_to(ARTIFACTS.resolve()):
        raise RuntimeError("Output must be a new regular file under artifacts/alpine")
    work = Path(tempfile.mkdtemp(prefix="build-", dir=ARTIFACTS))
    print(f"Build workspace: {work.relative_to(ROOT)}", flush=True)
    before = work / "original-tree"
    after = work / "output-tree"
    run(["xorriso", "-osirrox", "on", "-indev", str(original), "-extract", "/", str(before)], work / "extract-original.log")
    release = (before / ".alpine-release").read_text().strip()
    if release != "alpine-standard-3.24.3 261021":
        raise RuntimeError(f"Unexpected image release: {release}")
    config = work / "config"
    for name, edit in ((BIOS_CFG, modify_bios), (EFI_CFG, modify_efi)):
        dest = config / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(edit((before / name).read_text()))
    init = subprocess.run(["cpio", "-i", "--quiet", "--to-stdout", "init"],
                          input=gzip.decompress((before / "boot/initramfs-lts").read_bytes()),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    (work / "initramfs-init").write_bytes(init)
    if b'echo "$tty::respawn:/sbin/getty -L 0 $tty $term"' not in init or b"term=vt100" not in init:
        raise RuntimeError("Expected upstream serial getty generation missing")
    original_metadata = metadata(original, work / "original")
    guid = re.search(r"GPT disk GUID\s*:\s*([0-9a-f]{32})", original_metadata).group(1)
    run(["xorriso", "-indev", str(original), "-outdev", str(output),
         "-map", str(config / BIOS_CFG), "/" + BIOS_CFG,
         "-map", str(config / EFI_CFG), "/" + EFI_CFG,
         "-boot_image", "any", "replay",
         "-boot_image", "any", "gpt_disk_guid=" + guid,
         "-volume_date", "all_file_dates", STAMP,
         "-volume_date", "c", STAMP, "-volume_date", "m", STAMP,
         "-volume_date", "uuid", STAMP,
         "-commit", "-end"], work / "xorriso-build.log")
    output_metadata = metadata(output, work / "output")
    for evidence in (original_metadata, output_metadata):
        for token in ("MBR isohybrid cyl-align-on GPT", "BIOS  y", "UEFI  y",
                      "/boot/syslinux/isolinux.bin", "/boot/grub/efi.img", "0x80", "0xef"):
            if token not in evidence:
                raise RuntimeError(f"Required boot metadata missing: {token}")
    run(["xorriso", "-osirrox", "on", "-indev", str(output), "-extract", "/", str(after)], work / "extract-output.log")
    files = sorted(p.relative_to(before) for p in before.rglob("*") if p.is_file())
    if files != sorted(p.relative_to(after) for p in after.rglob("*") if p.is_file()):
        raise RuntimeError("ISO file list changed")
    changes = [str(p) for p in files if sha(before / p) != sha(after / p)]
    expected = {BIOS_CFG, EFI_CFG, "boot/syslinux/isolinux.bin", "boot/syslinux/boot.cat"}
    if not {BIOS_CFG, EFI_CFG}.issubset(changes) or not set(changes).issubset(expected):
        raise RuntimeError(f"Unexpected changed payloads: {changes}")
    # xorriso adjusts boot-info-table bytes 8..63 for the new ISO block layout.
    original_loader = (before / "boot/syslinux/isolinux.bin").read_bytes()
    output_loader = (after / "boot/syslinux/isolinux.bin").read_bytes()
    if original_loader[:8] + original_loader[64:] != output_loader[:8] + output_loader[64:]:
        raise RuntimeError("ISOLINUX changed outside its boot-info table")
    for name in (BIOS_CFG, EFI_CFG):
        if (after / name).read_bytes() != (config / name).read_bytes():
            raise RuntimeError("Output configuration mismatch")
    for iso in (original, output):
        with iso.open("rb") as stream:
            if stream.read(512)[510:] != b"\x55\xaa":
                raise RuntimeError("Missing MBR signature")
    digest = sha(output)
    output.with_suffix(output.suffix + ".sha256").write_text(f"{digest}  {output.name}\n")
    manifest = {"source_url": BASE_URL + SOURCE_NAME, "source_sha256": SOURCE_SHA,
                "source_release": release, "output": output.name, "output_size": output.stat().st_size,
                "output_sha256": digest, "workspace": str(work.relative_to(ROOT)),
                "changed_iso_files": changes, "unchanged_payload_count": len(files) - len(changes),
                "payload_sha256": {name: sha(after / name) for name in
                    ("boot/vmlinuz-lts", "boot/initramfs-lts", "boot/modloop-lts", "boot/grub/efi.img", "efi/boot/bootx64.efi")}}
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--output", type=Path, default=ARTIFACTS / OUTPUT_NAME)
    args = parser.parse_args()
    original = source()
    if not args.fetch_only:
        build(original, args.output.resolve())
