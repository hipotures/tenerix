#!/usr/bin/env python3
"""RN426-only panel interface. MIT; built on riplatt/truenas-rn426-panel.

Never imports upstream app/pages/installers. No storage or fan operations.
"""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
PIN = json.loads((ROOT / "provenance.json").read_text())
for _name, _sha in PIN["runtime_sha256"].items():
    if hashlib.sha256((ROOT / ".upstream" / _name).read_bytes()).hexdigest() != _sha:
        raise RuntimeError(f"Unreviewed upstream file: {_name}")
sys.path.insert(0, str(ROOT / ".upstream"))
from rnpanel.gpio import DnvMmioGpio
from rnpanel.lcd import LCD
from rnpanel.models import MODELS, detect_model
from rnpanel.msp430 import Msp430Buttons


def verify_hardware():
    """Stricter than upstream's CPU-only fallback; no override accepted."""
    if "RN_MODEL" in os.environ:
        raise RuntimeError("RN_MODEL overrides are forbidden")
    dmi = Path("/sys/class/dmi/id")
    if ((dmi / "sys_vendor").read_text().strip() != "NETGEAR"
            or (dmi / "product_name").read_text().strip() != "ReadyNAS 426"
            or (dmi / "board_name").read_text().strip() != "ReadyNAS 426"):
        raise RuntimeError("Exact NETGEAR ReadyNAS 426 DMI identity required")
    if "Intel(R) Atom(TM) CPU C3538" not in Path("/proc/cpuinfo").read_text():
        raise RuntimeError("Expected Atom C3538 CPU not found")
    pci = Path("/sys/bus/pci/devices/0000:00:1f.0")
    if (pci / "vendor").read_text().strip() != "0x8086" or (pci / "device").read_text().strip() != "0x19dc":
        raise RuntimeError("Expected Denverton LPC 8086:19dc not found")
    if detect_model() != "rn426":
        raise RuntimeError("Upstream model detection disagrees")


def find_i801_bus():
    buses = [p for p in Path("/sys/class/i2c-dev").glob("i2c-*")
             if "SMBus I801 adapter" in (p / "name").read_text()]
    if len(buses) != 1:
        raise RuntimeError("Exactly one named I801 adapter is required; no bus-number fallback")
    bus = int(buses[0].name.split("-")[1])
    if not Path(f"/dev/i2c-{bus}").is_char_device():
        raise RuntimeError("I801 character device missing")
    return bus


class SafeGpio(DnvMmioGpio):
    """Use upstream preflight/SPI transport with a narrow write boundary."""
    def __init__(self, spec):
        try:
            super().__init__(spec)
        except BaseException:
            self.close()
            raise

    def _preflight(self):
        super()._preflight()
        for sig in ("RST", "EN"):
            if not self._rd32(*self._pads[sig]) & 1:
                raise RuntimeError(f"{sig} is not already high; refusing recovery or initialization")

    def _set(self, pad, val):
        # Preserve RXDIS and all configuration bits; only TXSTATE changes.
        self._wr32(*pad, (self._rd32(*pad) & ~1) | (val & 1))

    def _wr32(self, comm, off, val):
        if (comm, off) not in self._pads.values():
            raise RuntimeError("Non-panel GPIO write rejected")
        if (comm, off) in (self._pads["RST"], self._pads["EN"]) and not val & 1:
            raise RuntimeError("Lowering shared RST/EN is forbidden")
        if (val ^ self._rd32(comm, off)) & ~3:
            # RXSTATE bit 1 is read-only and can change between reads.
            raise RuntimeError("GPIO configuration change rejected")
        super()._wr32(comm, off, val)

    def close(self):
        for buf in getattr(self, "_bufs", {}).values():
            if hasattr(buf, "close"):
                buf.close()
        self._bufs = {}
        for file in getattr(self, "_files", []):
            file.close()
        self._files = []


class SafeButtons(Msp430Buttons):
    """Reuse upstream interrupt/debounce logic; fail visibly on I/O errors."""
    def __init__(self, gpio):
        # Override upstream's bound function, not an adapter number.
        import rnpanel.msp430 as msp430
        msp430.find_i801_bus = find_i801_bus
        self.reads = 0
        self.last_bitmap = None
        self.in_events = False
        try:
            super().__init__(gpio)
        except BaseException:
            if hasattr(self, "fd"):
                os.close(self.fd)
            raise
        # Observe a stable idle line before arming; never read a stuck-low line at startup.
        self._armed = False
        self._high_since = None

    def _read(self, reg):
        if not self.in_events or reg != 0x04 or not self.gpio.int_active():
            raise RuntimeError("Only interrupt-triggered MSP430 register 0x04 reads allowed")
        try:
            value = super()._read(reg)
        except OSError as error:
            raise RuntimeError(f"MSP430 read failed: {error}") from error
        self.reads += 1
        self.last_bitmap = value
        if value & ~0x1f:
            raise RuntimeError(f"Unexpected MSP430 bitmap: {value:#04x}; stopping")
        return value

    def events(self, now):
        self.in_events = True
        try:
            return super().events(now)
        finally:
            self.in_events = False


class Panel:
    """One exclusive owner; use with Panel() as panel. Methods are synchronous."""
    def __init__(self):
        self.lock = None
        self.gpio = None
        self.reader = None
        try:
            verify_hardware()
            if subprocess.run(["systemctl", "is-active", "--quiet", "rn426-panel"], check=False).returncode == 0:
                raise RuntimeError("Upstream panel service is active; refusing a second controller")
            self.lock = os.open("/run/lock/rn426-panel.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            owner = subprocess.run(["fuser", "-s", "/dev/mem"], check=False)
            if owner.returncode != 1:
                raise RuntimeError("/dev/mem already has an owner or ownership check failed")
            # Do not trust direct callers to pass a different model or pin map.
            spec = dict(MODELS["rn426"], en_can_pulse=False)
            self.gpio = SafeGpio(spec)
            self.lcd = LCD(self.gpio, spec["geometry"], spec["init_seq"])
            self.lcd.init()
        except BaseException:
            self.close()
            raise

    def show(self, line1, line2):
        self.lcd.lines(str(line1), str(line2))

    def clear(self):
        self.show("", "")

    def sleep(self):
        self.lcd.sleep()

    def wake(self):
        self.lcd.wake()

    def buttons(self):
        """One nonblocking tick; caller ticks about every 5 ms."""
        if self.reader is None:
            self.reader = SafeButtons(self.gpio)
        return [{"PREV": "UP", "NEXT": "DOWN", "OK": "CENTER"}.get(a, a)
                for a in self.reader.events(time.monotonic())]

    def run(self, seconds=120, echo=False):
        if not math.isfinite(seconds) or not 0 < seconds <= 600:
            raise ValueError("Listen duration must be >0 and <=600 seconds")
        self.reader = self.reader or SafeButtons(self.gpio)
        counts = dict.fromkeys(("UP", "DOWN", "LEFT", "RIGHT", "CENTER"), 0)
        print(json.dumps({"status": "listening", "seconds": seconds}), flush=True)
        deadline = time.monotonic() + seconds
        try:
            while time.monotonic() < deadline:
                for event in self.buttons():
                    if event not in counts:
                        raise RuntimeError("Unknown MSP430 button bits; stopping")
                    counts[event] += 1
                    print(json.dumps({"button": event, "bitmap": self.reader.last_bitmap}), flush=True)
                    if echo:
                        self.show("Button", event)
                time.sleep(0.005)
        finally:
            print(json.dumps({"counts": counts, "mcu_reads": self.reader.reads}), flush=True)
        return counts

    def close(self):
        # Resource release only: no reset, pad restore, EN lowering or MCU operation.
        if self.reader is not None:
            os.close(self.reader.fd)
            self.reader = None
        if self.gpio is not None:
            self.gpio.close()
            self.gpio = None
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show")
    show.add_argument("line1")
    show.add_argument("line2")
    for name in ("clear", "sleep", "wake", "preflight"):
        commands.add_parser(name)
    listen = commands.add_parser("buttons", aliases=["run"])
    listen.add_argument("--seconds", type=float, default=120)
    listen.add_argument("--echo", action="store_true")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    if args.command == "preflight":
        verify_hardware()
        gpio = SafeGpio(dict(MODELS["rn426"], en_can_pulse=False))
        try:
            for c in sorted(gpio.COMMUNITIES):
                print(f"PADBAR {c}: {gpio._rd32(c, gpio.PADBAR_OFF):#010x}")
            for name, pad in list(gpio._pads.items()) + [("IRQ", gpio._int_pad)]:
                print(f"{name}: {gpio._rd32(*pad):#010x}")
            print("READ-ONLY PREFLIGHT PASSED; no GPIO writes")
        finally:
            gpio.close()
        return
    with Panel() as panel:
        if args.command == "show":
            started = time.monotonic()
            panel.show(args.line1, args.line2)
            print(json.dumps({"status": "frame sent", "frame_ms": round((time.monotonic() - started) * 1000, 2),
                              "visual_confirmation": "required"}), flush=True)
        elif args.command in ("buttons", "run"):
            panel.run(args.seconds, args.echo)
        else:
            getattr(panel, args.command)()


if __name__ == "__main__":
    main()
