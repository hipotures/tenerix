# RN426 descending fan test results, 2026-11-05

Source: [original JSONL measurements](evidence/descent-2026-11-05.jsonl), copied
from the NAS after the operator reported completion. This is the corrected
STOP/CONT experiment; the earlier failed TERM experiment is documented
separately in [the incident report](test-incident-2026-11-05.md).

The test ran from 08:45:43 to 09:22:37 UTC (09:45:43–10:22:37 Europe/Warsaw).
Initial readings were PWM80, 1513 RPM, highest CPU sensor 40 C, board 32 C,
and six SATA disks at 40–43 C. The current workload, ambient temperature,
acoustic level and disk activity were not independently recorded.

| PWM | Observed duration | Median RPM in final minute | Maximum CPU | Maximum board | Maximum disk |
| --- | --- | --- | --- | --- | --- |
| 72 | 10 minutes | 1436 | 40 C | 33 C | 44 C |
| 64 | 10 minutes | 1360 | 40 C | 33 C | 44 C |
| 56 | 10 minutes | 1280 | 41 C | 33 C | 45 C |
| 48 | 6 minutes 54 seconds | 1201 | 42 C | 33 C | 46 C |

The abort was triggered by disk `sdd` reaching **46 C**, a **3 C increase**
from its initial 43 C. The log's combined error message mentions both the
48 C absolute limit and the 3 C relative-rise limit; the absolute limit was
not reached. CPU at the abort sample was 40 C, board 33 C. No stage below
PWM48 ran. RPM figures exclude most of the transition from the previous duty.
SMART readings are cached between minute-scale refreshes, so repeated disk
values in five-second samples are not independent SMART measurements.

Recovery logged restoration of PWM80 and resumption of the original keeper.
A subsequent independent SSH read at approximately 09:41 UTC confirmed
PWM80, approximately 1513 RPM, normal keeper mode, CPU39 C, board33 C and disks
42–45 C. The original keeper process was present and no test process remained.
No permanent cooling settings were changed.

## Interpretation

Within this experiment, disk warming triggered the stop before the CPU or
board guards. The fan responded to reductions down to PWM48 without reaching
the experiment's 300 RPM lower guard. This does not establish the minimum
spinning duty, reliable startup duty, or whether PWM0 is usable.

The sequential stages share accumulated heat. Ten minutes per duty, without a
fixed workload or measured ambient temperature, cannot establish thermal
equilibrium or attribute all warming to the last PWM setting. Passing PWM56
for ten minutes does not qualify it for continuous operation.

A useful next measurement is a longer fixed-duty trial at PWM64 (approximately
1360 RPM here), retaining the current monitoring and restoration behavior,
to determine whether disk temperatures stabilize. PWM72 is a more conservative
candidate with a smaller speed reduction. No further experiment or permanent
policy change was launched as part of reading these results.
