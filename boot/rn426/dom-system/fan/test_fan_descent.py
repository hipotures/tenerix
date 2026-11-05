"""Simulated descent, keeper handoff and recovery; no hardware writes."""
import importlib.util
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('fan_descent', Path(__file__).with_name('fan-descent.py'))
fan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fan)


def sample(cpu=39, board=32, disk=44):
    return {'cpu_c': cpu, 'board_c': board, 'rpm': 1513,
            'disks_c': {'sda': disk}, 'pwm': 80, 'disk_age_s': 0}


class DescentTests(unittest.TestCase):
    def simulate(self, hw, **options):
        events, sent, writes = [], [], []
        clock, stopped = [0], [False]
        def sleep(seconds):
            clock[0] += seconds
        def send(pid, sig):
            self.assertEqual(pid, 123)
            self.assertIn(sig, (signal.SIGSTOP, signal.SIGCONT))
            stopped[0] = sig == signal.SIGSTOP
            sent.append(sig)
        hw.set_pwm.side_effect = lambda value: writes.append(value)
        hw.restore.side_effect = lambda value: writes.append(value)
        with patch.object(fan, 'keeper_processes', return_value=[123]), \
             patch.object(fan, 'paused', side_effect=lambda _: stopped[0]), \
             patch.object(fan.os, 'kill', side_effect=send), \
             patch.object(fan.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(fan.time, 'sleep', side_effect=sleep):
            try:
                fan.run_test(hw, events.append, minimum=72, **options)
            finally:
                self.assertEqual(sent, [signal.SIGSTOP, signal.SIGCONT])
                self.assertEqual(writes[-1], 80)
                self.assertNotIn(255, writes)
        return events, writes

    def hardware(self):
        hw = Mock()
        hw.pwm.return_value = 80
        hw.sample.return_value = sample()
        return hw

    def test_no_255_or_term_during_startup_completion_and_restore(self):
        events, writes = self.simulate(self.hardware())
        self.assertEqual(writes, [72, 80])
        readings = [e for e in events if e['event'] == 'sample']
        self.assertEqual(len(readings), 121)
        self.assertEqual(readings[-1]['stage_elapsed_s'], 600)
        self.assertEqual(events[-1]['keeper'], 'resumed')

    def test_interrupt_sensor_error_and_overheat_restore_original_controller(self):
        for failure in [fan.Abort('interrupt'), OSError('sensor missing'), sample(cpu=60), sample(disk=47)]:
            hw = self.hardware()
            hw.sample.side_effect = [sample(), failure]
            with self.subTest(failure=failure), self.assertRaises((fan.Abort, OSError)):
                self.simulate(hw)

    def test_all_sensors_and_relative_limits(self):
        for current in [sample(cpu=49), sample(board=39), sample(disk=47),
                        sample(cpu=60), sample(board=45), sample(disk=48)]:
            with self.subTest(current=current), self.assertRaises(fan.Abort):
                fan.check_limits(current, sample())
        fan.check_limits(sample(cpu=40, disk=45), sample())

    def test_steps_exclude_original_dwell_and_default_zero(self):
        self.assertEqual(list(fan.stages(80, 8, 8)), [72, 64, 56, 48, 40, 32, 24, 16, 8])
        self.assertEqual(list(fan.stages(80, 8, 0))[-1], 0)
        for args in [(8, 8, 8), (80, 0, 8), (80, 8, -1)]:
            with self.assertRaises(fan.Abort):
                list(fan.stages(*args))

    def test_missing_keeper_does_not_change_pwm(self):
        hw = self.hardware()
        with patch.object(fan, 'keeper_processes', return_value=[]), self.assertRaises(fan.Abort):
            fan.run_test(hw, lambda _: None)
        hw.set_pwm.assert_not_called()
        hw.restore.assert_not_called()

    def test_real_sensor_reader_rejects_stall_and_reads_smart_without_waking(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hw = fan.Hardware.__new__(fan.Hardware)
            hw.board, hw.cpu = root / 'board', root / 'cpu'
            hw.board.mkdir()
            hw.cpu.mkdir()
            for path, text in [('board/pwm2_enable', '1'), ('board/pwm2', '80'),
                               ('board/temp2_input', '32000'), ('board/fan2_input', '1513'),
                               ('cpu/temp1_input', '39000'), ('cpu/temp2_input', '37000')]:
                (root / path).write_text(text)
            hw.disk_at, hw.disk_values = fan.time.monotonic(), {'sda': 44}
            self.assertEqual(hw.sample(80)['cpu_c'], 39)
            for path, bad in [('board/fan2_input', '0'), ('cpu/temp2_input', '-128000'),
                              ('board/pwm2_enable', '0'), ('board/pwm2', '72')]:
                target = root / path
                old = target.read_text()
                target.write_text(bad)
                with self.subTest(path=path), self.assertRaises(fan.Abort):
                    hw.sample(80)
                target.write_text(old)
            hw.disk_at, hw.disks = None, [Path('/sys/block/sda')]
            with patch.object(fan.subprocess, 'run', return_value=Mock(returncode=2, stdout='standby')):
                with self.assertRaises(fan.Abort):
                    hw.sample(80)
            with patch.object(fan.subprocess, 'run', return_value=Mock(
                    returncode=0, stdout='{"temperature":{"current":44}}')) as smart:
                self.assertEqual(hw.sample(80)['disks_c'], {'sda': 44})
                self.assertIn('standby', smart.call_args.args[0])
            hw.restore(80)
            self.assertEqual(hw.pwm(), 80)


if __name__ == '__main__':
    unittest.main()
