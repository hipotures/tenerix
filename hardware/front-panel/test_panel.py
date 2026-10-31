"""Software-only regression tests: real upstream paths, fake device boundaries."""
import struct
import tempfile
import unittest
from unittest.mock import patch

import panel


class MemoryGpio(panel.SafeGpio):
    def __init__(self, bad=None):
        self.writes = []
        self.bad = bad or {}
        super().__init__(dict(panel.MODELS["rn426"], en_can_pulse=False))

    def _map(self, base):
        buf = bytearray(0x1000)
        struct.pack_into("<I", buf, 0x0c, 0x400)
        for sig, (comm, off) in panel.MODELS["rn426"]["pads"].items():
            if self.COMMUNITIES[comm] == base:
                struct.pack_into("<I", buf, off, 0x05000201)
        if base == self.COMMUNITIES["S"]:
            struct.pack_into("<I", buf, 0x570, 0x45000102)
        for (comm, off), value in self.bad.items():
            if self.COMMUNITIES[comm] == base:
                struct.pack_into("<I", buf, off, value)
        return buf

    def _wr32(self, comm, off, value):
        super()._wr32(comm, off, value)
        self.writes.append((comm, off, value))


class Buttons(panel.SafeButtons):
    def __init__(self):
        self.gpio = type("FakeIrq", (), {"int_active": lambda s: s.active})()
        self.gpio.active = False
        self._armed = False
        self._high_since = None
        self.reads = 0
        self.last_bitmap = None
        self.in_events = False


class SafetyTests(unittest.TestCase):
    def test_actual_lcd_init_never_lowers_en_or_reset(self):
        gpio = MemoryGpio()
        lcd = object.__new__(panel.LCD)
        lcd.gpio = gpio
        lcd.init_seq = panel.MODELS["rn426"]["init_seq"]
        lcd.init()
        lcd.sleep()
        lcd.wake()
        self.assertGreater(len(gpio.writes), 100)
        allowed = set(gpio._pads.values())
        for comm, off, value in gpio.writes:
            self.assertIn((comm, off), allowed)
            self.assertTrue(value & (1 << 9), "RXDIS must be preserved")
            if (comm, off) in (gpio._pads["EN"], gpio._pads["RST"]):
                self.assertTrue(value & 1)

    def test_guard_rejects_shared_low_irq_and_configuration_writes(self):
        gpio = MemoryGpio()
        for sig in ("EN", "RST"):
            with self.assertRaises(RuntimeError):
                gpio.set(sig, 0)
        with self.assertRaises(RuntimeError):
            gpio._wr32("S", 0x570, 0)
        comm, off = gpio._pads["CLK"]
        with self.assertRaises(RuntimeError):
            gpio._wr32(comm, off, gpio._rd32(comm, off) ^ (1 << 9))
        self.assertEqual(gpio.writes, [])

    def test_unsafe_initial_levels_refused_before_any_write(self):
        for sig in ("EN", "RST"):
            with self.assertRaisesRegex(RuntimeError, "not already high"):
                MemoryGpio({panel.MODELS["rn426"]["pads"][sig]: 0x05000200})
        with self.assertRaisesRegex(RuntimeError, "output driver disabled"):
            MemoryGpio({("N", 0x470): 0x05000301})

    def test_no_idle_mcu_reads_one_per_assertion_and_all_five_maps(self):
        btn = Buttons()
        with patch.object(panel.Msp430Buttons, "_read", return_value=0x1f) as read:
            self.assertEqual(btn.events(0), [])
            self.assertEqual(btn.events(0.06), [])
            read.assert_not_called()
            btn.gpio.active = True
            self.assertEqual(btn.events(0.07), ["LEFT", "RIGHT", "PREV", "NEXT", "OK"])
            self.assertEqual(btn.events(0.08), [])
            self.assertEqual(btn.reads, 1)
            btn.gpio.active = False
            btn.events(0.09)
            btn.events(0.15)
            btn.gpio.active = True
            btn.events(0.16)
            self.assertEqual(btn.reads, 2)
        with self.assertRaises(RuntimeError):
            btn.pressed()
        btn.in_events = True
        with self.assertRaises(RuntimeError):
            btn._read(0x02)

    def test_stuck_low_startup_does_not_read_and_errors_are_visible(self):
        btn = Buttons()
        btn.gpio.active = True
        with patch.object(panel.Msp430Buttons, "_read") as read:
            for tick in range(100):
                btn.events(tick / 200)
            read.assert_not_called()
        btn.gpio.active = False
        btn.events(1)
        btn.events(1.06)
        btn.gpio.active = True
        with patch.object(panel.Msp430Buttons, "_read", side_effect=OSError("I/O failure")):
            with self.assertRaisesRegex(RuntimeError, "MSP430 read failed"):
                btn.events(1.07)

    def test_public_names_and_bounded_loop(self):
        instance = object.__new__(panel.Panel)
        instance.reader = type("Reader", (), {"events": lambda s, now: ["PREV", "NEXT", "OK", "LEFT", "RIGHT"]})()
        self.assertEqual(instance.buttons(), ["UP", "DOWN", "CENTER", "LEFT", "RIGHT"])
        for seconds in (0, -1, 601, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                instance.run(seconds)

    def test_model_override_forbidden_before_opening_devices(self):
        with patch.dict(panel.os.environ, {"RN_MODEL": "rn426"}):
            with self.assertRaisesRegex(RuntimeError, "overrides are forbidden"):
                panel.verify_hardware()

    def test_missing_bus_never_falls_back(self):
        with patch.object(panel.Path, "glob", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "no bus-number fallback"):
                panel.find_i801_bus()

    def test_unknown_bitmap_aborts_instead_of_hiding_protocol_errors(self):
        btn = Buttons()
        btn.events(0)
        btn.events(0.06)
        btn.gpio.active = True
        with patch.object(panel.Msp430Buttons, "_read", return_value=0x81):
            with self.assertRaisesRegex(RuntimeError, "Unexpected MSP430 bitmap"):
                btn.events(0.07)

    def test_service_ownership_openrc_systemd_and_errors(self):
        result = type("Result", (), {})()
        def directory(path):
            return str(path) == self.init_directory
        with patch.object(panel.Path, "is_dir", directory), \
                patch.object(panel.Path, "exists", return_value=True), \
                patch.object(panel.shutil, "which", return_value="/sbin/tool"), \
                patch.object(panel.subprocess, "run", return_value=result) as run:
            for directory_name, command in (("/run/openrc", "rc-service"),
                                             ("/run/systemd/system", "systemctl")):
                self.init_directory = directory_name
                result.returncode = 3
                panel.check_service_owner()
                self.assertEqual(run.call_args.args[0][0], command)
                for code in (0, 1, 127):
                    result.returncode = code
                    with self.assertRaisesRegex(RuntimeError, "ownership check failed"):
                        panel.check_service_owner()
            self.init_directory = "unknown"
            with self.assertRaisesRegex(RuntimeError, "Unknown init"):
                panel.check_service_owner()

    def test_missing_openrc_service_still_requires_device_owner_check(self):
        with patch.object(panel.Path, "is_dir", return_value=True), \
                patch.object(panel.Path, "exists", return_value=False), \
                patch.object(panel.subprocess, "run") as run:
            panel.check_service_owner()
            run.assert_not_called()
        with tempfile.TemporaryFile() as lock, \
                patch.object(panel.os, "open", return_value=panel.os.dup(lock.fileno())), \
                patch.object(panel, "check_service_owner"), \
                patch.object(panel.subprocess, "run", return_value=type("R", (), {"returncode": 2})()):
            with self.assertRaisesRegex(RuntimeError, "ownership check failed"):
                panel.acquire_panel_lock()

    def test_fonts_use_complete_debian_or_alpine_pair(self):
        from PIL import ImageFont
        for root in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu"):
            with patch.object(panel.Path, "is_file", lambda path: str(path.parent) == root), \
                    patch.object(ImageFont, "truetype") as font:
                panel.PanelLCD(None, (4, 132), b"")
                self.assertEqual(font.call_args_list[0].args,
                                 (root + "/DejaVuSansMono-Bold.ttf", 16))
                self.assertEqual(font.call_args_list[1].args,
                                 (root + "/DejaVuSansMono.ttf", 13))
        with patch.object(panel.Path, "is_file", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "fonts are required"):
                panel.PanelLCD(None, (4, 132), b"")

    def test_second_owner_refused_before_gpio_is_opened(self):
        with tempfile.TemporaryFile() as lock:
            panel.fcntl.flock(lock.fileno(), panel.fcntl.LOCK_EX)
            # A new open file description is required to conflict with flock.
            fd = panel.os.open(f"/proc/self/fd/{lock.fileno()}", panel.os.O_RDWR)
            with patch.object(panel, "verify_hardware"), \
                    patch.object(panel.subprocess, "run", return_value=type("Result", (), {"returncode": 1})()), \
                    patch.object(panel.os, "open", return_value=fd), \
                    patch.object(panel, "SafeGpio") as gpio:
                with self.assertRaises(BlockingIOError):
                    panel.Panel()
                gpio.assert_not_called()


if __name__ == "__main__":
    unittest.main()
