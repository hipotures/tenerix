#!/usr/bin/env python3
"""Validate a built module against exact headers without loading any module."""

import argparse
import hashlib
import shutil
from pathlib import Path
import struct
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("module", nargs="?", default="build/it87.ko")
parser.add_argument("--kernel", default="6.12.107+deb13-amd64")
parser.add_argument("--headers", type=Path)
parser.add_argument("--stock", type=Path)
args = parser.parse_args()
KVER = args.kernel
KDIR = args.headers or Path("/lib/modules") / KVER / "build"
modinfo = shutil.which("modinfo")
if modinfo is None:
    raise SystemExit("kmod modinfo is required")


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def require(condition, message):
    if not condition:
        raise SystemExit(message)


module = Path(args.module).resolve()
require((KDIR / "include/config/kernel.release").read_text().strip() == KVER,
        "Wrong headers")
blob = module.read_bytes()
require(blob[:6] == b"\x7fELF\x02\x01", "Expected ELF64 little endian")
elf_type, machine = struct.unpack_from("<HH", blob, 16)
require((elf_type, machine) == (1, 62), "Expected x86-64 relocatable ELF")


info = {}
for field in ("name", "vermagic", "depends", "license", "signer", "srcversion"):
    info[field] = output(modinfo, "-F", field, str(module))
stock = args.stock or Path("/lib/modules") / KVER / "kernel/drivers/hwmon/it87.ko.xz"
require(info["vermagic"] == output(modinfo, "-F", "vermagic", str(stock)),
        "Stock and built module vermagic differ")
require(info["vermagic"].split()[0] == KVER, "Module release mismatch")
require(info["name"] == "it87" and info["license"] == "GPL", "Unexpected metadata")

exports = {}
for line in (KDIR / "Module.symvers").read_text().splitlines():
    crc, name, provider, export_type, *namespace = line.split()
    exports[name] = (int(crc, 16), provider, export_type, namespace)
undefined = []
for line in output("nm", "-u", str(module)).splitlines():
    kind, name = line.split()
    if kind == "U":
        undefined.append(name)
require(all(name in exports for name in undefined), "Unresolved strong symbol")

# These x86-64 kernels with CONFIG_MODVERSIONS use 64-byte modversion_info entries on amd64.
shoff = struct.unpack_from("<Q", blob, 40)[0]
entsize, count, strindex = struct.unpack_from("<HHH", blob, 58)
require(entsize == 64 and count > 0, "Unexpected ELF section format")
sections = [struct.unpack_from("<IIQQQQIIQQ", blob, shoff + i * entsize)
            for i in range(count)]
strings_section = sections[strindex]
names = blob[strings_section[4]:strings_section[4] + strings_section[5]]
versions = None
for section in sections:
    name = names[section[0]:].split(b"\0", 1)[0]
    if name == b"__versions":
        versions = blob[section[4]:section[4] + section[5]]
require(versions is not None and len(versions) % 64 == 0, "Missing/invalid CRC section")
checked = set()
for offset in range(0, len(versions), 64):
    crc = struct.unpack_from("<Q", versions, offset)[0]
    name = versions[offset + 8:offset + 64].split(b"\0", 1)[0].decode("ascii")
    require(name in exports and crc == exports[name][0], "CRC mismatch: " + name)
    checked.add(name)
require(set(undefined).issubset(checked), "Undefined symbol lacks version CRC")
require("module_layout" in checked, "Missing module_layout CRC")

print("ELF: ELF64 little-endian x86-64 relocatable")
for field, value in info.items():
    print(f"{field}: {value or '(empty)'}")
print(f"Strong undefined symbols resolved in exact Module.symvers: {len(undefined)}")
print(f"Version CRCs matched: {len(checked)}")
print("Providers: " + ", ".join(sorted({exports[n][1] for n in undefined})))
print("SHA256: " + hashlib.sha256(blob).hexdigest())
print("File-only validation; no module loaded; hardware safety not established.")
