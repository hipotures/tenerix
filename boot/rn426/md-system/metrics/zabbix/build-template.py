#!/usr/bin/env python3
"""Build (and optionally import) the Zabbix template "Tenerix NAS by Prometheus".

The template reads the NAS metrics that tenerix-metrics pushes into Prometheus: one HTTP
agent item fetches /federate every minute, everything else is a dependent item (Prometheus
pattern) or a dependent discovery rule (Prometheus to JSON). Addresses are macros, set on
the host: {$PROM.URL} (Prometheus base URL) and {$TENERIX.HOSTNAME} (host_name label).

  build-template.py                       write tenerix-nas-template.json next to this file
  build-template.py --import URL TOKENFILE  also import it through the Zabbix API
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import uuid
from pathlib import Path

NAME = 'Tenerix NAS by Prometheus'
GROUP = 'Templates/Storage'
MASTER = 'tenerix.federate'
NS = uuid.UUID('5b0c8f39-7f3e-4b7a-9e43-0d1c7b2d6a11')
T = f'/{NAME}/'          # prefix for trigger expressions


def uid(*parts: str) -> str:
    """Stable per object (re-import updates instead of duplicating), shaped as UUIDv4 as Zabbix requires."""
    return uuid.UUID(bytes=uuid.uuid5(NS, '|'.join(parts)).bytes, version=4).hex


def pattern(selector: str, discard_on_fail: bool = False, extra: list | None = None) -> list:
    output = ['function', 'sum'] if selector == 'tenerix_cpu_seconds_total' else ['value', '']
    steps = [{'type': 'PROMETHEUS_PATTERN', 'parameters': [selector, *output]}]
    if discard_on_fail:
        steps[0].update(error_handler='DISCARD_VALUE')
    return steps + (extra or [])


PER_SECOND = [{'type': 'CHANGE_PER_SECOND', 'parameters': ['']}]


def item(name, key, selector, *, value_type='FLOAT', units='', component='', triggers=(),
         discard=False, extra=None, description='', label=None):
    it = {'uuid': uid('item', key), 'name': name, 'type': 'DEPENDENT', 'key': key, 'delay': '0',
          'value_type': value_type, 'units': units, 'description': description,
          'preprocessing': pattern(selector, discard, extra), 'master_item': {'key': MASTER},
          'tags': [{'tag': 'component', 'value': component}] if component else []}
    if label:   # extract a label value instead of the sample value
        it['preprocessing'][0]['parameters'] = [selector, 'label', label]
        it['trends'] = '0'
    if value_type in ('CHAR', 'TEXT'):
        it['trends'] = '0'
    if triggers:
        it['triggers'] = [trigger(key, *t) for t in triggers]
    return it


def trigger(key, expression, name, priority, description=''):
    return {'uuid': uid('trigger', key, name), 'expression': expression, 'name': name,
            'priority': priority, 'description': description}


def proto(name, key, selector, **kw):
    it = item(name, key, selector, **kw)
    it['uuid'] = uid('proto', key)
    if 'triggers' in it:
        it['trigger_prototypes'] = it.pop('triggers')
        for tr in it['trigger_prototypes']:
            tr['uuid'] = uid('tproto', key, tr['name'])
    return it


def rule(name, key, metric, macros: dict, protos: list, trigger_protos=(), lifetime='7d'):
    return {'uuid': uid('rule', key), 'name': name, 'type': 'DEPENDENT', 'key': key, 'delay': '0',
            'lifetime': lifetime, 'master_item': {'key': MASTER},
            'preprocessing': [{'type': 'PROMETHEUS_TO_JSON', 'parameters': [metric]}],
            'lld_macro_paths': [{'lld_macro': m, 'path': f'$.labels.{label}'} for m, label in macros.items()],
            'item_prototypes': protos,
            'trigger_prototypes': [dict(t, uuid=uid('tproto', key, t['name'])) for t in trigger_protos]}


def last(key):
    return f'last({T}{key})'


def build() -> dict:
    sel = lambda metric, **labels: metric + '{' + ','.join(f'{k}="{v}"' for k, v in labels.items()) + '}'
    host = '{$TENERIX.HOSTNAME}'
    items = [
        {'uuid': uid('item', MASTER), 'name': 'Prometheus federate: tenerix metrics', 'type': 'HTTP_AGENT',
         'key': MASTER, 'delay': '1m', 'history': '0', 'value_type': 'TEXT', 'trends': '0',
         'url': '{$PROM.URL}/federate',
         'query_fields': [{'name': 'match[]', 'value': '{job="tenerix-metrics",host_name="' + host + '"}'}],
         'description': 'All tenerix_* samples of the NAS from Prometheus; every other item depends on it.',
         'tags': [{'tag': 'component', 'value': 'raw'}],
         'triggers': [trigger(MASTER, f'nodata({T}{MASTER},{{$TENERIX.NODATA}})=1',
                              'No metrics from the NAS for {$TENERIX.NODATA}', 'HIGH',
                              'tenerix-metrics stopped, the NAS is down, or Prometheus/Collector does not receive it.')]},
        item('Uptime', 'tenerix.uptime', 'tenerix_uptime_seconds', units='uptime', component='system',
             triggers=[(f'{last("tenerix.uptime")}<600', 'NAS has been restarted (uptime < 10m)', 'WARNING')]),
        item('Load average (1m)', 'tenerix.load1', sel('tenerix_load', period='1m'), component='system'),
        item('Load average (15m)', 'tenerix.load15', sel('tenerix_load', period='15m'), component='system',
             triggers=[(f'min({T}tenerix.load15,30m)>{{$TENERIX.LOAD.WARN}}', 'High load average on the NAS', 'WARNING')]),
        item('Memory total', 'tenerix.mem.total', 'tenerix_memory_total_bytes', value_type='UNSIGNED', units='B', component='memory'),
        item('Memory available', 'tenerix.mem.available', 'tenerix_memory_available_bytes', value_type='UNSIGNED', units='B',
             component='memory',
             triggers=[(f'max({T}tenerix.mem.available,10m)<{{$TENERIX.MEM.AVAIL.MIN}}', 'Low available memory on the NAS', 'WARNING')]),
        item('Swap free', 'tenerix.swap.free', 'tenerix_swap_free_bytes', value_type='UNSIGNED', units='B', component='memory'),
        item('CPU idle', 'tenerix.cpu.idle', sel('tenerix_cpu_seconds_total', mode='idle'), units='s/s', component='cpu',
             extra=PER_SECOND, description='Idle CPU seconds per second (4 = all four cores idle).'),
        item('CPU iowait', 'tenerix.cpu.iowait', sel('tenerix_cpu_seconds_total', mode='iowait'), units='s/s', component='cpu',
             extra=PER_SECOND),
        item('CPU time, all modes', 'tenerix.cpu.total', 'tenerix_cpu_seconds_total', units='s/s', component='cpu',
             extra=PER_SECOND, description='CPU seconds per second over all modes = number of cores.'),
        {'uuid': uid('item', 'tenerix.cpu.util'), 'name': 'CPU utilization', 'type': 'CALCULATED',
         'key': 'tenerix.cpu.util', 'delay': '1m', 'value_type': 'FLOAT', 'units': '%',
         'params': '100-100*last(//tenerix.cpu.idle)/last(//tenerix.cpu.total)',
         'description': 'Same name as in the Linux templates, so dashboard "Top hosts" widgets list the NAS.',
         'tags': [{'tag': 'component', 'value': 'cpu'}]},
        {'uuid': uid('item', 'tenerix.mem.util'), 'name': 'Memory utilization', 'type': 'CALCULATED',
         'key': 'tenerix.mem.util', 'delay': '1m', 'value_type': 'FLOAT', 'units': '%',
         'params': '100-100*last(//tenerix.mem.available)/last(//tenerix.mem.total)',
         'tags': [{'tag': 'component', 'value': 'memory'}]},
        item('Kernel release', 'tenerix.kernel', 'tenerix_kernel_info', value_type='CHAR', component='system', label='release',
             triggers=[(f'change({T}tenerix.kernel)=1', 'NAS kernel changed', 'INFO')]),
        item('Alpine release', 'tenerix.os', 'tenerix_os_info', value_type='CHAR', component='system', label='version_id'),
        item('Agent version', 'tenerix.agent.version', 'tenerix_agent_info', value_type='CHAR', component='agent', label='version'),
        item('NFS server up', 'tenerix.nfs.up', 'tenerix_nfs_server_up', value_type='UNSIGNED', component='nfs',
             triggers=[(f'{last("tenerix.nfs.up")}=0', 'NFS server is not running', 'HIGH')]),
        item('NFS clients', 'tenerix.nfs.clients', 'tenerix_nfs_clients', value_type='UNSIGNED', component='nfs'),
        item('NFS exports', 'tenerix.nfs.exports', 'tenerix_nfs_exports', value_type='UNSIGNED', component='nfs'),
    ]

    rules = [
        rule('RAID arrays', 'tenerix.md.discovery', 'tenerix_md_up', {'{#MD}': 'md', '{#LEVEL}': 'level'}, [
            proto('RAID {#MD} ({#LEVEL}): up', 'tenerix.md.up[{#MD}]', sel('tenerix_md_up', md='{#MD}'),
                  value_type='UNSIGNED', component='raid',
                  triggers=[(f'{last("tenerix.md.up[{#MD}]")}=0', 'RAID {#MD} is not running', 'DISASTER')]),
            proto('RAID {#MD}: degraded disks', 'tenerix.md.degraded[{#MD}]', sel('tenerix_md_degraded', md='{#MD}'),
                  value_type='UNSIGNED', component='raid', discard=True,
                  triggers=[(f'{last("tenerix.md.degraded[{#MD}]")}>0', 'RAID {#MD} is degraded', 'HIGH')]),
            proto('RAID {#MD}: disks expected', 'tenerix.md.disks[{#MD}]', sel('tenerix_md_disks', md='{#MD}'),
                  value_type='UNSIGNED', component='raid'),
            proto('RAID {#MD}: disks in sync', 'tenerix.md.active[{#MD}]', sel('tenerix_md_disks_active', md='{#MD}'),
                  value_type='UNSIGNED', component='raid'),
            proto('RAID {#MD}: disks failed', 'tenerix.md.failed[{#MD}]', sel('tenerix_md_disks_failed', md='{#MD}'),
                  value_type='UNSIGNED', component='raid',
                  triggers=[(f'{last("tenerix.md.failed[{#MD}]")}>0', 'RAID {#MD} has a failed disk', 'HIGH')]),
            proto('RAID {#MD}: sync running', 'tenerix.md.sync[{#MD}]', sel('tenerix_md_sync_active', md='{#MD}'),
                  value_type='UNSIGNED', component='raid', discard=True,
                  triggers=[(f'{last("tenerix.md.sync[{#MD}]")}=1', 'RAID {#MD}: resync/check running', 'INFO')]),
            proto('RAID {#MD}: mismatch sectors', 'tenerix.md.mismatch[{#MD}]', sel('tenerix_md_mismatch_sectors', md='{#MD}'),
                  value_type='UNSIGNED', component='raid', discard=True,
                  triggers=[(f'{last("tenerix.md.mismatch[{#MD}]")}>0', 'RAID {#MD} reports mismatched sectors', 'WARNING')]),
        ], trigger_protos=[{
            'expression': f'{last("tenerix.md.active[{#MD}]")}<{last("tenerix.md.disks[{#MD}]")}',
            'name': 'RAID {#MD}: fewer disks in sync than expected', 'priority': 'HIGH'}]),

        rule('LUKS volumes', 'tenerix.crypt.discovery', 'tenerix_crypt_open', {'{#CRYPTDEV}': 'device'}, [
            proto('LUKS {#CRYPTDEV}: open', 'tenerix.crypt.open[{#CRYPTDEV}]', sel('tenerix_crypt_open', device='{#CRYPTDEV}'),
                  value_type='UNSIGNED', component='storage',
                  triggers=[(f'{last("tenerix.crypt.open[{#CRYPTDEV}]")}=0',
                             'Encrypted volume on {#CRYPTDEV} is locked (needs arch01.py mount)', 'AVERAGE')]),
        ]),

        rule('File systems', 'tenerix.fs.discovery', 'tenerix_fs_size_bytes',
             {'{#MOUNT}': 'mountpoint', '{#FSTYPE}': 'fstype', '{#FSDEV}': 'device'}, [
            proto('FS {#MOUNT}: size', 'tenerix.fs.size[{#MOUNT}]', sel('tenerix_fs_size_bytes', mountpoint='{#MOUNT}'),
                  value_type='UNSIGNED', units='B', component='storage'),
            proto('FS {#MOUNT}: available', 'tenerix.fs.avail[{#MOUNT}]', sel('tenerix_fs_avail_bytes', mountpoint='{#MOUNT}'),
                  value_type='UNSIGNED', units='B', component='storage'),
            proto('FS {#MOUNT}: read-only', 'tenerix.fs.ro[{#MOUNT}]', sel('tenerix_fs_readonly', mountpoint='{#MOUNT}'),
                  value_type='UNSIGNED', component='storage',
                  triggers=[(f'{last("tenerix.fs.ro[{#MOUNT}]")}=1', 'File system {#MOUNT} is read-only', 'HIGH')]),
            {'uuid': uid('proto', 'tenerix.fs.pused[{#MOUNT}]'), 'name': 'FS {#MOUNT}: used, %', 'type': 'CALCULATED',
             'key': 'tenerix.fs.pused[{#MOUNT}]', 'delay': '1m', 'value_type': 'FLOAT', 'units': '%',
             'params': '100-100*last(//tenerix.fs.avail[{#MOUNT}])/last(//tenerix.fs.size[{#MOUNT}])',
             'tags': [{'tag': 'component', 'value': 'storage'}],
             'trigger_prototypes': [
                 {'uuid': uid('tproto', 'pused-warn'), 'name': 'File system {#MOUNT} is over {$TENERIX.FS.PUSED.WARN}% full',
                  'expression': f'{last("tenerix.fs.pused[{#MOUNT}]")}>{{$TENERIX.FS.PUSED.WARN}}', 'priority': 'WARNING'},
                 {'uuid': uid('tproto', 'pused-crit'), 'name': 'File system {#MOUNT} is over {$TENERIX.FS.PUSED.CRIT}% full',
                  'expression': f'{last("tenerix.fs.pused[{#MOUNT}]")}>{{$TENERIX.FS.PUSED.CRIT}}', 'priority': 'HIGH'}]},
        ]),

        rule('File system errors', 'tenerix.fserr.discovery', 'tenerix_fs_errors',
             {'{#MOUNT}': 'mountpoint', '{#MEMBER}': 'member', '{#ETYPE}': 'type'}, [
            proto('FS {#MOUNT} {#MEMBER}: {#ETYPE} errors', 'tenerix.fs.errors[{#MOUNT},{#MEMBER},{#ETYPE}]',
                  sel('tenerix_fs_errors', mountpoint='{#MOUNT}', member='{#MEMBER}', type='{#ETYPE}'),
                  value_type='UNSIGNED', component='storage',
                  triggers=[(f'{last("tenerix.fs.errors[{#MOUNT},{#MEMBER},{#ETYPE}]")}>0',
                             'File system {#MOUNT}: {#ETYPE} errors on {#MEMBER}', 'HIGH',
                             'Btrfs device stats / ext4 errors_count is non-zero; check dmesg and run a scrub.')]),
        ]),

        rule('Disks (SMART)', 'tenerix.disk.discovery', 'tenerix_disk_info',
             {'{#DISK}': 'disk', '{#SERIAL}': 'serial', '{#MODEL}': 'model'}, [
            proto('Disk {#DISK} ({#SERIAL}): SMART healthy', 'tenerix.disk.healthy[{#SERIAL}]',
                  sel('tenerix_disk_smart_healthy', serial='{#SERIAL}'), value_type='UNSIGNED', component='disk', discard=True,
                  triggers=[(f'{last("tenerix.disk.healthy[{#SERIAL}]")}=0', 'Disk {#DISK} ({#SERIAL}) fails SMART health', 'DISASTER')]),
            proto('Disk {#DISK} ({#SERIAL}): temperature', 'tenerix.disk.temp[{#SERIAL}]',
                  sel('tenerix_disk_temperature_celsius', serial='{#SERIAL}'), units='°C', component='disk', discard=True,
                  triggers=[(f'min({T}tenerix.disk.temp[{{#SERIAL}}],10m)>{{$TENERIX.DISK.TEMP.WARN}}',
                             'Disk {#DISK} ({#SERIAL}) is hot', 'WARNING'),
                            (f'min({T}tenerix.disk.temp[{{#SERIAL}}],10m)>{{$TENERIX.DISK.TEMP.CRIT}}',
                             'Disk {#DISK} ({#SERIAL}) is very hot', 'HIGH')]),
            proto('Disk {#DISK} ({#SERIAL}): helium level', 'tenerix.disk.helium[{#SERIAL}]',
                  sel('tenerix_smart_helium_level', serial='{#SERIAL}'), value_type='UNSIGNED', component='disk', discard=True,
                  description='Normalized SMART 22 (100 = full); vendor failure threshold 25.',
                  triggers=[(f'{last("tenerix.disk.helium[{#SERIAL}]")}<{{$TENERIX.HELIUM.WARN}}',
                             'Disk {#DISK} ({#SERIAL}) is losing helium', 'WARNING'),
                            (f'{last("tenerix.disk.helium[{#SERIAL}]")}<{{$TENERIX.HELIUM.CRIT}}',
                             'Disk {#DISK} ({#SERIAL}) helium level near failure threshold', 'HIGH')]),
            proto('Disk {#DISK} ({#SERIAL}): reallocated sectors', 'tenerix.disk.realloc[{#SERIAL}]',
                  sel('tenerix_smart_reallocated_sectors', serial='{#SERIAL}'), value_type='UNSIGNED', component='disk', discard=True,
                  triggers=[(f'change({T}tenerix.disk.realloc[{{#SERIAL}}])>0',
                             'Disk {#DISK} ({#SERIAL}): new reallocated sectors', 'WARNING')]),
            proto('Disk {#DISK} ({#SERIAL}): pending sectors', 'tenerix.disk.pending[{#SERIAL}]',
                  sel('tenerix_smart_pending_sectors', serial='{#SERIAL}'), value_type='UNSIGNED', component='disk', discard=True,
                  triggers=[(f'{last("tenerix.disk.pending[{#SERIAL}]")}>0',
                             'Disk {#DISK} ({#SERIAL}) has pending sectors', 'HIGH')]),
            proto('Disk {#DISK} ({#SERIAL}): offline uncorrectable', 'tenerix.disk.uncorr[{#SERIAL}]',
                  sel('tenerix_smart_offline_uncorrectable_sectors', serial='{#SERIAL}'), value_type='UNSIGNED',
                  component='disk', discard=True,
                  triggers=[(f'{last("tenerix.disk.uncorr[{#SERIAL}]")}>0',
                             'Disk {#DISK} ({#SERIAL}) has uncorrectable sectors', 'HIGH')]),
            proto('Disk {#DISK} ({#SERIAL}): UDMA CRC errors', 'tenerix.disk.crc[{#SERIAL}]',
                  sel('tenerix_smart_udma_crc_errors', serial='{#SERIAL}'), value_type='UNSIGNED', component='disk', discard=True,
                  triggers=[(f'change({T}tenerix.disk.crc[{{#SERIAL}}])>0',
                             'Disk {#DISK} ({#SERIAL}): new CRC errors (cable/backplane)', 'WARNING')]),
            proto('Disk {#DISK} ({#SERIAL}): power-on hours', 'tenerix.disk.hours[{#SERIAL}]',
                  sel('tenerix_smart_power_on_hours', serial='{#SERIAL}'), value_type='UNSIGNED', component='disk', discard=True),
            proto('Disk {#DISK} ({#SERIAL}): standby', 'tenerix.disk.standby[{#SERIAL}]',
                  sel('tenerix_disk_standby', serial='{#SERIAL}'), value_type='UNSIGNED', component='disk', discard=True),
        ], lifetime='30d'),

        rule('Network interfaces', 'tenerix.net.discovery', 'tenerix_net_received_bytes_total', {'{#IF}': 'interface'}, [
            proto('Interface {#IF}: bits received', 'tenerix.net.in[{#IF}]',
                  sel('tenerix_net_received_bytes_total', interface='{#IF}'), units='bps', component='network',
                  extra=PER_SECOND + [{'type': 'MULTIPLIER', 'parameters': ['8']}]),
            proto('Interface {#IF}: bits sent', 'tenerix.net.out[{#IF}]',
                  sel('tenerix_net_transmitted_bytes_total', interface='{#IF}'), units='bps', component='network',
                  extra=PER_SECOND + [{'type': 'MULTIPLIER', 'parameters': ['8']}]),
            proto('Interface {#IF}: receive errors', 'tenerix.net.rxerr[{#IF}]',
                  sel('tenerix_net_receive_errors_total', interface='{#IF}'), value_type='UNSIGNED', component='network',
                  triggers=[(f'change({T}tenerix.net.rxerr[{{#IF}}])>0', 'Interface {#IF}: receive errors', 'WARNING')]),
            proto('Interface {#IF}: transmit errors', 'tenerix.net.txerr[{#IF}]',
                  sel('tenerix_net_transmit_errors_total', interface='{#IF}'), value_type='UNSIGNED', component='network',
                  triggers=[(f'change({T}tenerix.net.txerr[{{#IF}}])>0', 'Interface {#IF}: transmit errors', 'WARNING')]),
            proto('Interface {#IF}: link speed', 'tenerix.net.speed[{#IF}]',
                  sel('tenerix_net_link_speed_megabits', interface='{#IF}'), value_type='UNSIGNED', units='Mbps',
                  component='network', discard=True,
                  triggers=[(f'change({T}tenerix.net.speed[{{#IF}}])<0', 'Interface {#IF}: link speed dropped', 'WARNING')]),
        ]),

        rule('Temperature sensors', 'tenerix.temp.discovery', 'tenerix_hwmon_temperature_celsius',
             {'{#CHIP}': 'chip', '{#SENSOR}': 'sensor'}, [
            proto('{#CHIP} {#SENSOR}: temperature', 'tenerix.hwmon.temp["{#CHIP}","{#SENSOR}"]',
                  sel('tenerix_hwmon_temperature_celsius', chip='{#CHIP}', sensor='{#SENSOR}'), units='°C', component='sensors',
                  triggers=[(f'min({T}tenerix.hwmon.temp["{{#CHIP}}","{{#SENSOR}}"],5m)>{{$TENERIX.HWMON.TEMP.WARN}}',
                             '{#CHIP} {#SENSOR} is hot', 'WARNING'),
                            (f'min({T}tenerix.hwmon.temp["{{#CHIP}}","{{#SENSOR}}"],5m)>{{$TENERIX.HWMON.TEMP.CRIT}}',
                             '{#CHIP} {#SENSOR} is very hot', 'HIGH')]),
        ]),

        rule('Fans', 'tenerix.fan.discovery', 'tenerix_hwmon_fan_rpm', {'{#CHIP}': 'chip', '{#FAN}': 'sensor'}, [
            proto('{#CHIP} {#FAN}: speed', 'tenerix.hwmon.fan["{#CHIP}","{#FAN}"]',
                  sel('tenerix_hwmon_fan_rpm', chip='{#CHIP}', sensor='{#FAN}'), units='rpm', component='sensors',
                  triggers=[(f'max({T}tenerix.hwmon.fan["{{#CHIP}}","{{#FAN}}"],3m)<{{$TENERIX.FAN.MIN}}',
                             'Fan {#FAN} is stopped or too slow', 'HIGH')]),
        ]),

        rule('Metric collectors', 'tenerix.collector.discovery', 'tenerix_agent_collector_up', {'{#COLLECTOR}': 'collector'}, [
            proto('Collector {#COLLECTOR}: up', 'tenerix.collector.up[{#COLLECTOR}]',
                  sel('tenerix_agent_collector_up', collector='{#COLLECTOR}'), value_type='UNSIGNED', component='agent',
                  triggers=[(f'max({T}tenerix.collector.up[{{#COLLECTOR}}],10m)=0',
                             'tenerix-metrics collector {#COLLECTOR} is failing', 'WARNING',
                             'See /var/log/tenerix-metrics.log on the NAS.')]),
        ]),
    ]

    macros = {
        '{$PROM.URL}': ('http://prometheus:9090', 'Prometheus base URL (set on the host).'),
        '{$TENERIX.HOSTNAME}': ('tenerix', 'host_name label of the NAS in Prometheus.'),
        '{$TENERIX.NODATA}': ('5m', 'Alert when no metrics arrive for this long.'),
        '{$TENERIX.LOAD.WARN}': ('8', ''),
        '{$TENERIX.MEM.AVAIL.MIN}': ('268435456', 'Bytes.'),
        '{$TENERIX.FS.PUSED.WARN}': ('90', ''),
        '{$TENERIX.FS.PUSED.CRIT}': ('95', ''),
        '{$TENERIX.DISK.TEMP.WARN}': ('50', ''),
        '{$TENERIX.DISK.TEMP.CRIT}': ('55', ''),
        '{$TENERIX.HELIUM.WARN}': ('95', ''),
        '{$TENERIX.HELIUM.CRIT}': ('40', ''),
        '{$TENERIX.HWMON.TEMP.WARN}': ('75', ''),
        '{$TENERIX.HWMON.TEMP.CRIT}': ('85', ''),
        '{$TENERIX.FAN.MIN}': ('300', 'rpm'),
    }
    template = {
        'uuid': uid('template', NAME), 'template': NAME, 'name': NAME,
        'description': 'Tenerix NAS (RN426, Alpine) health from tenerix-metrics via Prometheus /federate. '
                       'Generated by boot/rn426/md-system/metrics/zabbix/build-template.py.',
        'groups': [{'name': GROUP}],
        'items': items, 'discovery_rules': rules,
        'tags': [{'tag': 'class', 'value': 'storage'}],
        'macros': [{'macro': m, 'value': v, 'description': d} for m, (v, d) in macros.items()],
    }
    return {'zabbix_export': {'version': '7.0', 'template_groups': [{'uuid': uid('group', GROUP), 'name': GROUP}],
                              'templates': [template]}}


def api(url: str, token: str, method: str, params) -> object:
    body = json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params, 'id': 1}).encode()
    req = urllib.request.Request(url.rstrip('/') + '/api_jsonrpc.php', data=body, method='POST',
                                 headers={'Content-Type': 'application/json-rpc', 'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        reply = json.load(resp)
    if 'error' in reply:
        raise SystemExit(f"{method}: {reply['error'].get('message')} {reply['error'].get('data')}")
    return reply['result']


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--import', dest='target', nargs=2, metavar=('URL', 'TOKENFILE'))
    parser.add_argument('--out', default=str(Path(__file__).with_name('tenerix-nas-template.json')))
    args = parser.parse_args()
    export = build()
    text = json.dumps(export, indent=1, ensure_ascii=False) + '\n'
    Path(args.out).write_text(text)
    print(f'wrote {args.out}')
    if args.target:
        url, tokenfile = args.target
        token = Path(tokenfile).expanduser().read_text().strip()
        yes = {'createMissing': True, 'updateExisting': True}
        rules = {'template_groups': yes, 'templates': yes, 'items': dict(yes, deleteMissing=True),
                 'discoveryRules': dict(yes, deleteMissing=True), 'triggers': dict(yes, deleteMissing=True)}
        api(url, token, 'configuration.import', {'format': 'json', 'source': text, 'rules': rules})
        print(f'imported "{NAME}" into {url}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
