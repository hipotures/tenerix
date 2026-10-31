"""Software-only safety checks; all device boundaries are temporary files."""
import contextlib
import importlib.util
import io
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('fan_test', Path(__file__).with_name('fan-test.py'))
fan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fan)


class FanTestSafety(unittest.TestCase):
    def exercise(self, fault=False, only80=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cpu, board, proc = root / 'cpu', root / 'board', root / 'proc'
            for p in (cpu, board, proc):
                p.mkdir()
            for p, value in ((cpu / 'temp1_input', '35000'), (board / 'temp2_input', '30000'),
                             (board / 'fan2_input', '2014'), (board / 'pwm2', '128'),
                             (board / 'pwm2_enable', '1')):
                p.write_text(value)
            release = root / 'release'
            release.write_text('6.18.58-0-lts')
            module = root / 'module'
            module.write_bytes(b'simulated-module')
            paths = {'/proc/sys/kernel/osrelease': release,
                     '/tmp/tenerix-alpine-hw/it87.ko': module, '/proc': proc}
            original_write = Path.write_text
            writes = []

            def write(path, text, *args, **kwargs):
                if path == board / 'pwm2':
                    writes.append(int(text))
                    if fault and int(text) == 80:
                        original_write(cpu / 'temp1_input', '70000')
                return original_write(path, text, *args, **kwargs)

            with patch.object(fan, 'MODULE_SHA', hashlib.sha256(module.read_bytes()).hexdigest()), \
                    patch.object(fan, 'Path', side_effect=lambda value: paths[value]), \
                    patch.object(fan, 'named_hwmon', side_effect=lambda name: cpu if name == 'coretemp' else board), \
                    patch.object(fan, 'open', side_effect=lambda *a: open(root / 'lock', 'a')), \
                    patch.object(fan.signal, 'signal'), patch.object(fan.time, 'sleep'), \
                    patch.object(Path, 'write_text', write), contextlib.redirect_stdout(io.StringIO()):
                if fault:
                    with self.assertRaisesRegex(RuntimeError, 'CPU temperature'):
                        fan.main(pwm80_only=only80)
                else:
                    fan.main(pwm80_only=only80)
            self.assertEqual((board / 'pwm2_enable').read_text(), '1')
            self.assertEqual(writes, [112, 96, 80, 255] if fault else
                             ([80, 128] if only80 else [112, 96, 80, 128, 128]))

    def test_normal_completion_restores_baseline(self):
        self.exercise()

    def test_short_pwm80_test_restores_baseline(self):
        self.exercise(only80=True)

    def test_temperature_failure_sets_full_speed(self):
        self.exercise(fault=True)


if __name__ == '__main__':
    unittest.main()
