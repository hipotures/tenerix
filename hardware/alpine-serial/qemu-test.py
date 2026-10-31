#!/usr/bin/env python3
"""Actual login/shell test of a read-only ISO in an isolated TCG guest."""
import argparse
import json
from pathlib import Path
import re
import time

import pexpect

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--mode", choices=("cdrom", "usb", "serial-input"), required=True)
parser.add_argument("--iso", type=Path, default=ROOT / "artifacts/alpine/alpine-3.24.3-rn426-serial-x86_64.iso")
parser.add_argument("--log-dir", type=Path, default=ROOT / "hardware/alpine-serial/evidence")
args = parser.parse_args()
iso = args.iso.resolve(strict=True)
if not iso.is_file() or not iso.is_relative_to((ROOT / "artifacts/alpine").resolve()):
    raise RuntimeError("Only a local ISO artifact is accepted; no device paths")
args.log_dir.mkdir(parents=True, exist_ok=True)
command = ["qemu-system-x86_64", "-machine", "pc,accel=tcg", "-cpu", "max", "-smp", "2",
           "-m", "2048", "-display", "none", "-serial", "stdio", "-monitor", "none",
           "-nic", "none", "-no-reboot"]
if args.mode == "usb":
    command += ["-device", "qemu-xhci,id=xhci",
                "-drive", f"if=none,format=raw,readonly=on,id=liveusb,file={iso}",
                "-device", "usb-storage,drive=liveusb,bootindex=1"]
else:
    command += ["-boot", "order=d,strict=on", "-drive", f"if=ide,media=cdrom,format=raw,readonly=on,file={iso}"]
start = time.monotonic()
result = {"mode": args.mode, "acceleration": "TCG", "command": command, "passed": False}
raw_dir = ROOT / "artifacts/alpine/qemu-raw"
raw_dir.mkdir(parents=True, exist_ok=True)
raw_log = raw_dir / f"qemu-{args.mode}.log"
with raw_log.open("w", newline="") as log:
    child = pexpect.spawn(command[0], command[1:], encoding="utf-8", codec_errors="replace", timeout=300, echo=False)
    child.logfile_read = log
    try:
        # Only the additional serial-input test sends anything before login.
        # CD-ROM and USB tests must boot with no bootloader/keyboard input.
        if args.mode == "serial-input":
            child.expect("boot:")
            child.send("lts\r")
            child.expect(r"lts(?:\x1b\[[0-?]*[ -/]*[@-~])*\r*\n")
            result["bootloader_input_echoed"] = True
        child.expect(r"Linux version 6\.18\.58-0-lts")
        result["kernel_on_serial"] = True
        child.expect(r"(?:localhost|alpine) login: ")
        result["seconds_to_login"] = round(time.monotonic() - start, 2)
        result["login_prompt"] = True
        child.send("root\r")
        child.expect(r"(?:localhost|alpine):[^\r\n]*# ")
        result["interactive_root_login"] = True
        command_line = ("uname -a; cat /proc/cmdline; cat /etc/alpine-release; cat /etc/inittab; "
                        "stty -F /dev/ttyS0 -a; tty; id -u; "
                        "if test -f /etc/securetty; then cat /etc/securetty; else echo SECURETTY_FILE_ABSENT; fi; "
                        "rc-status; netstat -lnt; cat /proc/mounts; "
                        "printf '\\nRN426_%s\\n' TEST_DONE")
        child.send(command_line + "\r")
        child.expect(r"\r*\nRN426_TEST_DONE\r*\n")
        observed = child.before.replace("\r", "")
        for token in ("console=tty0 console=ttyS0,115200n8", "3.24.3", "Linux localhost 6.18.58-0-lts",
                      "ttyS0::respawn:/sbin/getty -L 0 ttyS0 vt100", "speed 115200 baud", "/dev/ttyS0"):
            if token not in observed:
                raise RuntimeError(f"Missing guest evidence: {token}")
        if not re.search(r"[\r\n]0\r?\n", observed):
            raise RuntimeError("Root UID was not demonstrated")
        result["getty"] = "ttyS0::respawn:/sbin/getty -L 0 ttyS0 vt100"
        result["baud"] = 115200
        result["shell_commands_verified"] = True
        child.expect(r"(?:localhost|alpine):[^\r\n]*# ")
        child.send("poweroff\r")
        child.expect(pexpect.EOF, timeout=60)
        child.close()
        if child.exitstatus != 0:
            raise RuntimeError(f"QEMU exit status {child.exitstatus}")
        result["passed"] = True
    except BaseException as error:
        result["error"] = str(error)
        raise
    finally:
        if child.isalive():
            child.close(force=True)
        log.flush()
        text = raw_log.read_bytes().decode("utf-8", errors="replace")
        text = re.sub(r"\r+\n", "\n", text).replace("\r", "")
        text = re.sub(r"\x1b7[^\x1b]*\x1b8", "", text)
        text = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|[78@-_])", "", text)
        (args.log_dir / f"qemu-{args.mode}.log").write_text("\n".join(line.rstrip() for line in text.splitlines()) + "\n")
        result["elapsed_seconds"] = round(time.monotonic() - start, 2)
        (args.log_dir / f"qemu-{args.mode}.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
