#!/usr/bin/env python3
"""Unit tests for tenerix-metrics on a fake /proc and /sys tree (no NAS needed).

Run: python3 -m unittest boot/rn426/md-system/metrics/test_tenerix_metrics.py
"""
import importlib.machinery
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
_loader = importlib.machinery.SourceFileLoader('tenerix_metrics', str(HERE / 'tenerix-metrics'))
_spec = importlib.util.spec_from_loader('tenerix_metrics', _loader)
tm = importlib.util.module_from_spec(_spec)
sys.modules['tenerix_metrics'] = tm
_loader.exec_module(tm)

SMART_ACTIVE = """\
=== START OF READ SMART DATA SECTION ===
SMART overall-health self-assessment test result: PASSED

ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
  4 Start_Stop_Count        0x0012   097   097   000    Old_age   Always       -       1357
  5 Reallocated_Sector_Ct   0x0033   100   100   001    Pre-fail  Always       -       2
  9 Power_On_Hours          0x0012   095   095   000    Old_age   Always       -       41381
 22 Helium_Level            0x0023   093   093   025    Pre-fail  Always       -       100
194 Temperature_Celsius     0x0002   037   037   000    Old_age   Always       -       41 (Min/Max 24/55)
197 Current_Pending_Sector  0x0022   100   100   000    Old_age   Always       -       0
"""
SMART_STANDBY = "Device is in STANDBY mode, exit(2)\n"
SMART_USB = "/dev/sdg: Unknown USB bridge [0x13fe:0x5200 (0x100)]\nPlease specify device type with the -d option.\n"


class FakeContext(tm.Context):
    def __init__(self, root, commands=None, statvfs=None):
        super().__init__(root)
        self.commands = commands or {}
        self.calls = []
        self._statvfs = statvfs or {}

    def run(self, argv, timeout=30):
        self.calls.append(argv)
        out = self.commands.get(tuple(argv), '')
        if isinstance(out, Exception):
            raise out
        return subprocess.CompletedProcess(argv, 0, out, '')

    def statvfs(self, path):
        return self._statvfs[path]

    def uname(self):
        return os.uname_result(('Linux', 'nas', '6.18.60-0-lts', '#1 SMP', 'x86_64'))


class Statvfs:
    def __init__(self, blocks, free, avail, files=0, ffree=0, frsize=4096):
        self.f_blocks, self.f_bfree, self.f_bavail = blocks, free, avail
        self.f_files, self.f_ffree, self.f_frsize = files, ffree, frsize


class TreeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.write('/proc/stat', 'cpu  100 0 50 1000 5 0 0 0 0 0\nbtime 1700000000\n')
        self.write('/etc/hostname', 'nas\n')

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, path, text):
        p = self.root / path.lstrip('/')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text) if isinstance(text, bytes) else p.write_text(text)

    def ctx(self, **kw):
        return FakeContext(self.root, **kw)

    @staticmethod
    def by_name(samples):
        out = {}
        for s in samples:
            out.setdefault(s.name.removeprefix('tenerix_'), []).append((dict(s.labels), s.value))
        return out


class MdTests(TreeTest):
    def md(self, name, state='clean', disks=3, members=('in_sync',) * 3, action='idle', completed='none',
           degraded='0'):
        base = f'/sys/block/{name}/md'
        for key, value in dict(array_state=state, level='raid5', raid_disks=str(disks), degraded=degraded,
                               sync_action=action, sync_completed=completed, mismatch_cnt='0').items():
            self.write(f'{base}/{key}', value + '\n')
        for i, member in enumerate(members):
            self.write(f'{base}/dev-sd{chr(97 + i)}3/state', member + '\n')

    def test_healthy_array(self):
        self.md('md2')
        m = self.by_name(tm.MdCollector().collect(self.ctx()))
        self.assertEqual(m['md_up'], [({'md': 'md2', 'level': 'raid5'}, 1)])
        self.assertEqual(m['md_disks_active'][0][1], 3)
        self.assertEqual(m['md_degraded'][0][1], 0)
        self.assertEqual(m['md_sync_active'], [({'md': 'md2', 'action': 'idle'}, 0)])
        self.assertNotIn('md_sync_progress_ratio', m)

    def test_degraded_array_with_resync(self):
        self.md('md2', members=('in_sync', 'faulty', 'in_sync'), degraded='1', action='recover',
                completed='250 / 1000')
        m = self.by_name(tm.MdCollector().collect(self.ctx()))
        self.assertEqual(m['md_disks_active'][0][1], 2)
        self.assertEqual(m['md_disks_failed'][0][1], 1)
        self.assertEqual(m['md_degraded'][0][1], 1)
        self.assertEqual(m['md_sync_active'][0], ({'md': 'md2', 'action': 'recover'}, 1))
        self.assertEqual(m['md_sync_progress_ratio'][0][1], 0.25)

    def test_inactive_array_is_down(self):
        self.md('md9', state='inactive')
        m = self.by_name(tm.MdCollector().collect(self.ctx()))
        self.assertEqual(m['md_up'][0][1], 0)


class CryptTests(TreeTest):
    BLKID = '/dev/md0: TYPE="ext4"\n/dev/md2: UUID="x" TYPE="crypto_LUKS"\n'

    def test_closed_volume_reports_zero(self):
        c = tm.CryptCollector()
        ctx = self.ctx(commands={('blkid',): self.BLKID})
        c.start(ctx)
        self.assertEqual(self.by_name(c.collect(ctx))['crypt_open'], [({'device': 'md2'}, 0)])

    def test_open_volume_and_blkid_runs_only_at_start(self):
        self.write('/sys/block/dm-0/dm/uuid', 'CRYPT-LUKS2-abc-data\n')
        self.write('/sys/block/dm-0/dm/name', 'data\n')
        self.write('/sys/block/dm-0/slaves/md2', '')
        c = tm.CryptCollector()
        ctx = self.ctx(commands={('blkid',): self.BLKID})
        c.start(ctx)
        list(c.collect(ctx))
        m = self.by_name(c.collect(ctx))
        self.assertEqual(m['crypt_open'], [({'device': 'md2', 'name': 'data'}, 1)])
        self.assertEqual(ctx.calls.count(['blkid']), 1)


class FilesystemTests(TreeTest):
    def setUp(self):
        super().setUp()
        self.write('/proc/filesystems', 'nodev\tsysfs\nnodev\ttmpfs\n\text4\n\tbtrfs\nnodev\tnfsd\n')
        self.write('/proc/mounts', '\n'.join([
            'sysfs /sys sysfs rw 0 0',
            'tmpfs /run tmpfs rw 0 0',
            '/dev/md0 / ext4 rw,noatime 0 0',
            '/dev/mapper/data /mnt/data btrfs rw,noatime 0 0',
            '/dev/mapper/data /mnt/snap btrfs ro,noatime 0 0',
            'nfsd /proc/fs/nfsd nfsd rw 0 0']) + '\n')
        self.write('/sys/fs/ext4/md0/errors_count', '3\n')

    def test_only_real_file_systems_once_per_device_with_error_counters(self):
        btrfs = '[/dev/mapper/data].write_io_errs    0\n[/dev/mapper/data].corruption_errs  5\n'
        ctx = self.ctx(commands={('btrfs', 'device', 'stats', '/mnt/data'): btrfs},
                       statvfs={'/': Statvfs(100, 40, 30, 1000, 900), '/mnt/data': Statvfs(1000, 500, 500)})
        m = self.by_name(tm.FilesystemCollector().collect(ctx))
        self.assertEqual(sorted(l['mountpoint'] for l, _ in m['fs_size_bytes']), ['/', '/mnt/data'])
        self.assertIn(({'mountpoint': '/', 'device': '/dev/md0', 'fstype': 'ext4'}, 30 * 4096),
                      m['fs_avail_bytes'])
        errors = {(l['mountpoint'], l['type']): v for l, v in m['fs_errors']}
        self.assertEqual(errors, {('/', 'errors'): 3, ('/mnt/data', 'write_io'): 0,
                                  ('/mnt/data', 'corruption'): 5})
        self.assertEqual([l['mountpoint'] for l, _ in m['fs_files']], ['/'])


class NetworkTests(TreeTest):
    def iface(self, name, carrier, rx=10, speed='1000'):
        base = f'/sys/class/net/{name}'
        if carrier is not None:
            self.write(f'{base}/carrier', carrier + '\n')
        self.write(f'{base}/speed', speed + '\n')
        for stat in ('rx_bytes', 'tx_bytes', 'rx_packets', 'tx_packets',
                     'rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped'):
            self.write(f'{base}/statistics/{stat}', f'{rx}\n')

    def test_only_connected_interfaces(self):
        self.iface('lo', '1')
        self.iface('eth0', '0')
        self.iface('eth1', None)          # down: reading carrier fails
        self.iface('eth3', '1', rx=1234)
        samples = list(tm.NetworkCollector().collect(self.ctx()))
        self.assertEqual({dict(s.labels)['interface'] for s in samples}, {'eth3'})
        m = self.by_name(samples)
        self.assertEqual(m['net_received_bytes'], [({'interface': 'eth3'}, 1234)])
        self.assertTrue(all(s.kind == tm.COUNTER for s in samples if 'speed' not in s.name))


class HwmonTests(TreeTest):
    def test_skips_missing_diode_and_unused_fan_header(self):
        self.write('/sys/class/hwmon/hwmon1/name', 'it8613\n')
        self.write('/sys/class/hwmon/hwmon1/temp1_input', '-128000\n')
        self.write('/sys/class/hwmon/hwmon1/temp2_input', '32000\n')
        self.write('/sys/class/hwmon/hwmon1/fan2_input', '1500\n')
        self.write('/sys/class/hwmon/hwmon1/fan3_input', '0\n')
        self.write('/sys/class/hwmon/hwmon1/in7_input', '3212\n')
        self.write('/sys/class/hwmon/hwmon1/in7_label', '3VSB\n')
        c = tm.HwmonCollector()
        m = self.by_name(c.collect(self.ctx()))
        self.assertEqual(m['hwmon_temperature_celsius'], [({'chip': 'it8613', 'sensor': 'temp2'}, 32.0)])
        self.assertEqual(m['hwmon_fan_rpm'], [({'chip': 'it8613', 'sensor': 'fan2'}, 1500.0)])
        self.assertEqual(m['hwmon_voltage_volts'], [({'chip': 'it8613', 'sensor': '3VSB'}, 3.212)])
        # a fan that turned once and then stops keeps being reported, as 0
        self.write('/sys/class/hwmon/hwmon1/fan2_input', '0\n')
        m = self.by_name(c.collect(self.ctx()))
        self.assertEqual(m['hwmon_fan_rpm'], [({'chip': 'it8613', 'sensor': 'fan2'}, 0.0)])


class SmartTests(TreeTest):
    def disk(self, name, removable='0', serial='Z2KAKLYT'):
        self.write(f'/sys/block/{name}/removable', removable + '\n')
        self.write(f'/sys/block/{name}/device/model', 'WDC WD120EMFZ-11\n')
        raw = serial.encode()
        self.write(f'/sys/block/{name}/device/vpd_pg80', bytes([0, 0x80, 0, len(raw)]) + raw)

    def cmd(self, disk):
        return ('smartctl', '-n', 'standby', '-H', '-A', f'/dev/{disk}')

    def test_active_disk(self):
        self.disk('sda')
        ctx = self.ctx(commands={self.cmd('sda'): SMART_ACTIVE})
        m = self.by_name(tm.SmartCollector().collect(ctx))
        labels = {'disk': 'sda', 'serial': 'Z2KAKLYT'}
        self.assertEqual(m['disk_temperature_celsius'], [(labels, 41)])
        self.assertEqual(m['smart_reallocated_sectors'], [(labels, 2)])
        self.assertEqual(m['smart_helium_level'], [(labels, 93)])   # normalized VALUE, not raw
        self.assertEqual(m['disk_smart_healthy'], [(labels, 1)])
        self.assertEqual(m['disk_standby'], [(labels, 0)])
        self.assertEqual(m['disk_info'], [(dict(labels, model='WDC WD120EMFZ-11'), 1)])

    def test_standby_keeps_counters_but_not_temperature(self):
        self.disk('sda')
        c = tm.SmartCollector()
        ctx = self.ctx(commands={self.cmd('sda'): SMART_ACTIVE})
        list(c.collect(ctx))
        ctx.commands[self.cmd('sda')] = SMART_STANDBY
        m = self.by_name(c.collect(ctx))
        self.assertEqual(m['disk_standby'][0][1], 1)
        self.assertEqual(m['smart_reallocated_sectors'][0][1], 2)
        self.assertNotIn('disk_temperature_celsius', m)

    def test_removable_and_usb_bridge_skipped(self):
        self.disk('sdg', removable='1')
        self.disk('sdh')
        c = tm.SmartCollector()
        ctx = self.ctx(commands={self.cmd('sdh'): SMART_USB})
        self.assertEqual(list(c.collect(ctx)), [])
        list(c.collect(ctx))
        self.assertEqual(ctx.calls, [list(self.cmd('sdh'))])   # sdg never, sdh only once


class NfsTests(TreeTest):
    TCP = ('  sl  local_address rem_address   st\n'
           '   0: 00000000:0801 00000000:0000 0A 00000000:00000000\n')

    def test_server_up(self):
        self.write('/proc/fs/nfsd/threads', '8\n')
        self.write('/proc/net/tcp', self.TCP)
        self.write('/var/lib/nfs/etab', '/mnt/data\t192.168.1.0/24(rw)\n')
        self.write('/proc/fs/nfsd/clients/1/info', '')
        m = self.by_name(tm.NfsCollector().collect(self.ctx()))
        self.assertEqual(m['nfs_server_up'][0][1], 1)
        self.assertEqual(m['nfs_exports'][0][1], 1)
        self.assertEqual(m['nfs_clients'][0][1], 1)

    def test_server_down(self):
        m = self.by_name(tm.NfsCollector().collect(self.ctx()))
        self.assertEqual(m['nfs_server_up'][0][1], 0)


class OtlpTests(unittest.TestCase):
    def test_payload(self):
        snap = tm.Snapshot(2_000, 1_000, [
            tm.gauge('fs_free_bytes', 5, 'By', mountpoint='/'),
            tm.gauge('fs_free_bytes', 7, 'By', mountpoint='/mnt/data'),
            tm.counter('cpu_seconds', 1.5, 's', mode='user'),
        ], {'host.name': 'nas'})
        p = tm.otlp_payload(snap)
        rm = p['resourceMetrics'][0]
        self.assertEqual(rm['resource']['attributes'], [{'key': 'host.name', 'value': {'stringValue': 'nas'}}])
        metrics = {m['name']: m for m in rm['scopeMetrics'][0]['metrics']}
        free = metrics['tenerix_fs_free_bytes']
        self.assertEqual(free['unit'], 'By')
        self.assertEqual([d['asInt'] for d in free['gauge']['dataPoints']], ['5', '7'])
        cpu = metrics['tenerix_cpu_seconds']['sum']
        self.assertTrue(cpu['isMonotonic'])
        self.assertEqual(cpu['aggregationTemporality'], 2)
        self.assertEqual(cpu['dataPoints'][0]['startTimeUnixNano'], '1000')
        self.assertEqual(cpu['dataPoints'][0]['asDouble'], 1.5)

    def test_mixed_units_rejected(self):
        snap = tm.Snapshot(1, 0, [tm.gauge('x', 1, 'By'), tm.gauge('x', 1, 's')], {})
        with self.assertRaises(ValueError):
            tm.otlp_payload(snap)

    def test_label_named_name_allowed(self):
        self.assertEqual(dict(tm.gauge('crypt_open', 1, name='data').labels), {'name': 'data'})


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Counting(tm.Collector):
    name = 'slow'
    interval = 600

    def __init__(self):
        self.calls = 0
        self.fail = False

    def collect(self, ctx):
        self.calls += 1
        if self.fail:
            raise OSError('boom')
        return [tm.gauge('thing', self.calls)]


class ListSink(tm.Sink):
    name = 'list'

    def __init__(self, ok=True):
        self.snapshots, self.ok = [], ok

    def publish(self, snapshot):
        self.snapshots.append(snapshot)
        return self.ok


class AgentTests(TreeTest):
    def agent(self, collector, sink):
        clock = Clock()
        return tm.Agent(self.ctx(), [collector], [sink], clock=clock, monotonic=clock), clock

    def test_slow_collector_cached_between_reads(self):
        c, sink = Counting(), ListSink()
        agent, clock = self.agent(c, sink)
        agent.cycle()
        clock.t += 60
        snap = agent.cycle()
        self.assertEqual(c.calls, 1)
        m = self.by_name(snap.samples)
        self.assertEqual(m['thing'][0][1], 1)
        self.assertEqual(m['agent_collector_age_seconds'][0][1], 60)
        clock.t += 540
        agent.cycle()
        self.assertEqual(c.calls, 2)
        self.assertEqual(snap.resource['host.name'], 'nas')
        self.assertEqual(snap.boot_ns, 1700000000 * 10**9)

    def test_failing_collector_drops_its_samples_only(self):
        c, sink = Counting(), ListSink()
        agent, clock = self.agent(c, sink)
        agent.cycle()
        c.fail = True
        clock.t += 600
        with unittest.mock.patch.object(tm, 'log'):
            snap = agent.cycle()
        m = self.by_name(snap.samples)
        self.assertNotIn('thing', m)
        self.assertEqual(m['agent_collector_up'], [({'collector': 'slow'}, 0)])

    def test_export_result_reported_next_cycle(self):
        c, sink = Counting(), ListSink(ok=False)
        agent, clock = self.agent(c, sink)
        agent.cycle()
        snap = agent.cycle()
        self.assertEqual(self.by_name(snap.samples)['agent_export_success'], [({'sink': 'list'}, 0)])


class ConfigTests(unittest.TestCase):
    def test_parse(self):
        with tempfile.NamedTemporaryFile('w', suffix='.conf', delete=False) as f:
            f.write('# comment\nendpoint = http://collector:4318/v1/metrics\ninterval = 120\ndisable = smart, nfs\n')
        try:
            cfg = tm.load_config(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(cfg.endpoint, 'http://collector:4318/v1/metrics')
        self.assertEqual(cfg.interval, 120)
        self.assertEqual(cfg.disabled, ('smart', 'nfs'))
        self.assertNotIn('smart', [c.name for c in tm.build_collectors(cfg.disabled)])

    def test_interval_below_minimum_rejected(self):
        with tempfile.NamedTemporaryFile('w', suffix='.conf', delete=False) as f:
            f.write('interval = 10\n')
        try:
            with self.assertRaises(SystemExit):
                tm.load_config(f.name)
        finally:
            os.unlink(f.name)

    def test_missing_file_and_unknown_collector(self):
        self.assertEqual(tm.load_config('/nonexistent').endpoint, '')
        with self.assertRaises(SystemExit):
            tm.build_collectors(['nope'])

    def test_registry_names_unique(self):
        names = [c.name for c in tm.REGISTRY]
        self.assertEqual(len(names), len(set(names)))


class TextSinkTests(unittest.TestCase):
    def test_counter_suffix(self):
        out = io.StringIO()
        tm.TextSink(out).publish(tm.Snapshot(0, 0, [tm.counter('cpu_seconds', 2, 's', mode='user')], {}))
        self.assertEqual(out.getvalue(), 'tenerix_cpu_seconds_total{mode="user"} 2\n')


if __name__ == '__main__':
    unittest.main()
