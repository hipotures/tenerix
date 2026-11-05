# Aborted fan descent experiment, 2026-11-05

The operator requested descending PWM steps from the existing PWM80 setting,
with ten minutes per step and CPU, board and disk temperature monitoring.

A temporary script was uploaded and launched on the NAS. The original keeper
was terminated to prevent competing writes. Its termination handler wrote
PWM255. The experiment then aborted with `Expected existing manual PWM mode 1`
before recording any lower-PWM stage; its cleanup also wrote PWM255. This
caused unwanted full-speed fan noise. The intended first PWM72 stage did not
run. Local simulations had not modeled the real driver's full-duty mode
readback during this handoff, and did not establish hardware correctness.

The operator immediately requested cancellation and restoration. The experiment
was terminated, PWM80 restored, and the original keeper restarted. Subsequent
live verification confirmed PWM80, approximately 1510 RPM, normal keeper mode,
CPU 37–38 C, board 32 C, and disk temperatures 40–44 C. No descent-test process
remained. There is one observed active tach channel, fan2; fan3 reads zero.
These readings do not establish the physical fan count.

The unqualified experimental script was removed from the development changes.
No permanent controller or configuration change was made on the NAS. Further
experiments must first account for the existing keeper's termination behavior,
real full-duty mode semantics, and the operator's requested restoration behavior.

After restoration, the operator asked for the script and launch instructions.
A corrected version was prepared: STOP/CONT handoff replaces TERM, and cleanup
restores the original PWM and resumes the original keeper. Simulation coverage
now explicitly rejects TERM or PWM255 during the test lifecycle. The corrected
script was uploaded without launching a second hardware experiment.
