# tenerix-metrics

Pushes NAS health metrics to an OpenTelemetry Collector over OTLP/HTTP (JSON), every 60 s.
Python standard library only; started by OpenRC `local` like the panel and fan services.

```text
collectors ──> Agent (schedule, cache, own health) ──> Snapshot ──> sinks
 md, crypt, filesystem, network, diskio,                            otlp (Collector)
 hwmon, system, nfs, info (1 h), smart (10 min)                     text / json (--print, --json)
```

| Collector | Source | What |
| --- | --- | --- |
| `md` | `/sys/block/md*/md` | array up, disks expected/active/failed, degraded, resync action and progress, mismatches |
| `crypt` | `/sys/block/dm-*`, `blkid` once at start | each LUKS device open or not |
| `filesystem` | `/proc/mounts`, `statvfs`, `btrfs device stats`, `/sys/fs/ext4` | every block-device file system: size/free/avail, inodes, read-only, error counters |
| `network` | `/sys/class/net` | traffic, errors, drops, link speed of interfaces with carrier only |
| `diskio` | `/proc/diskstats` | reads/writes, bytes, busy time of disks, md and dm |
| `hwmon` | `/sys/class/hwmon` | temperatures, fans, voltages (unconnected inputs skipped) |
| `system` | `/proc` | load, memory, swap, CPU time, uptime |
| `nfs` | `/proc/fs/nfsd`, `/proc/net/tcp*`, `etab` | server up, threads, exports, clients |
| `info` | `uname`, `/etc/os-release` | kernel and OS release (read hourly) |
| `smart` | `smartctl -n standby -H -A` | health, temperature, helium level, reallocated/pending/uncorrectable sectors, CRC errors, hours; never spins up a sleeping disk |

All metric names start with `tenerix_`; the resource carries `host.name`, `service.name=tenerix-metrics`.
Kernel counters are cumulative sums starting at boot (Prometheus adds `_total`).
The agent also reports `tenerix_agent_collector_up`, `..._age_seconds` and `tenerix_agent_export_success`.
Nothing is queued: a failed export is lost and the next cycle carries current values.

## Install

```sh
install -m 755 tenerix-metrics /usr/local/sbin/
install -m 755 tenerix-metrics.start tenerix-metrics.stop /etc/local.d/
install -D -m 644 metrics.conf.example /etc/tenerix/metrics.conf   # then set endpoint
tenerix-metrics --once --print --no-send    # inspect, send nothing
tenerix-metrics --once                      # one real export
/etc/local.d/tenerix-metrics.start
```

Log: `/var/log/tenerix-metrics.log` (state changes only).

## Extending

* Data source: subclass `Collector` (name, interval, `collect()` yielding `gauge()`/`counter()`),
  decorate with `@register`. Event sources start a thread in `start()`.
* Destination (e.g. the front panel): subclass `Sink` and add it in `build_sinks()`.

Tests: `python3 -m unittest test_tenerix_metrics.py`.
