# Encoder faults and recorded outcomes

The differential-drive preset can force the digital A or B input of either
wheel encoder low or high. The shaft and quadrature generator continue
running normally. The mask is between the generator and the routed STM32
GPIO input. The firmware, timer counters, drivetrain, and motor commands
retain their normal paths. This is an ideal digital mask. Electrical
behavior such as a floating or shorted wire is outside the model.

## Scheduled scenarios

These are optional fields under the existing version 1 robot `scenario`.
Keep its other fields, including duration, observer, pose and loads.

```json
{
  "encoder_fault_evidence": true,
  "encoder_faults": [
    {"channel": "right.a", "level": 0, "start_s": 1, "end_s": 2}
  ]
}
```

Use `left.a`, `left.b`, `right.a`, or `right.b`. Levels are integer 0
or 1. Start is inclusive and end is exclusive. Both times must be within
the configured duration on the 25 µs physics grid. A scenario may contain
up to 16 intervals total across
the four channels. Intervals on each channel must be ordered and
nonoverlapping. Distinct channels can overlap. A nonempty fault
schedule enables evidence automatically. Set `encoder_fault_evidence`
explicitly to record an unfaulted baseline or enable live controls before
any faults are scheduled. With both features off, the original CSV
schema and values are preserved.

At time zero, scheduled masks are initialized before firmware executes.
At a later physics tick, the scheduled mask changes first. The input
immediately resolves to the forced level when a mask takes effect, or to
the last physical level when the mask clears. The quadrature generator
then emits the physical transitions due on that tick, preserving their
order. A mask change may therefore create a GPIO edge if the driven level
differs from the previous delivered level. Clearing coincident with a
physical edge can produce a reconnection edge followed by that physical
edge at the same virtual timestamp. Abutting intervals on one channel
resolve directly to the new forced level. Missed transitions are never
replayed and the MCU count is never repaired. An unaffected channel
continues delivering its normal transitions.

Each of the four channels gains five CSV columns. For right A these are
`enc_right_a_physical_edges`, `enc_right_a_delivered_edges`,
`enc_right_a_physical_level`, `enc_right_a_delivered_level`, and
`enc_right_a_forced_level`. Edge counts are cumulative, unsigned counts
of toggles since reset. Delivered counts include reconnection edges and
count GPIO boundary transitions, independent of how the timer interprets
them. Sampled levels are 0 or 1 and the mask is −1 for pass-through.
The original `encoder_l` and `encoder_r` are still signed physical
quadrature counts. `fw_total_l` and `fw_total_r` come from the optional
firmware observer. The setup run saves the schedule in `config.json`.
Level snapshots are sampled at 1 ms and can miss very short masks. The
cumulative counts retain intervening activity.

## Live control and reproduction

Enable encoder evidence in **Scenario**, or import the scheduled JSON,
then prepare a live simulation. **Queue fault** applies a live override
at the next available 100 ms boundary. While paused, it waits for
**Resume**. **Clear override** restores the scheduled mask for that
channel if one is active, or connects the current physical signal
otherwise. Live overrides win over scheduled masks on their channel.
The UI shows pending commands and their actual application timestamps.
The replay readout distinguishes cumulative physical and GPIO edges and
shows the mask in effect at the sampled time.

At a live boundary, scheduled changes and physical edges for the tick
and its CSV sample have already occurred. If a load command and a fault
command both apply there, the worker applies load first, then fault.
The next sample reflects the live change. A reset starts a fresh machine
and reinstates only the original configuration schedule. The passive
PLL168 discovery profile has no robot encoder controls.

A fault-enabled live run uses event log version 2. Applied fault
changes have `sequence`, integer `at_ns`, `channel` and `level`
(`null` clears an override). Load entries keep `right_Nms`.
The `unapplied_faults` list carries a queued change canceled by stop,
reset, completion, failure or shutdown and its reason. The initial
configuration hash includes the scheduled intervals. Legacy sessions
continue to use version 1. Retain the exact ELF and all three live
artifacts. For completed or stopped recordings, use:

```sh
python3 setup/live.py --elf path/to/original.elf --config path/to/config.json \
  --events path/to/events.json --output setup/out/fault-reproduction
```

## Assertions

A version 1 JSON suite has a `version` of 1 and a nonempty `checks`
array. Each check specifies `name`, `metric`, `start_s` and `end_s`.
The interval must be inside the recorded sample range. Do not use
0 for the start when the first sample is at 0.001 s.

| Metric | Additional fields | Signal and measurement |
| --- | --- | --- |
| `tracking_mae` | `wheel` (left or right), `max` in rad/s | Time-weighted absolute error between model wheel speed and optional firmware reference |
| `peak_current` | `wheel`, `max` in A | Peak absolute sampled model motor current |
| `pwm_saturation` | `wheel`, `duty_fraction` in [0, 1], `max` in seconds | Time with observed PWM duty at or above the threshold |
| `encoder_activity` | `channel`, `min_physical_edges`, `min_delivered_edges`, `max_delivered_edges` | Physical and GPIO counter differences, with both endpoints on recorded samples. Setting both delivered limits to 0 checks that the pin stayed stuck while the physical channel moved. |

The first three metrics use sample-and-hold over `[start_s,end_s)`.
Activity uses counter differences over `(start_s,end_s]`. Missing
signals, invalid duty fractions, invalid counters or malformed inputs
produce an error. Speed tracking requires the firmware observer to
provide a reference. Units follow the exact column names in the recording
schema. The evaluator writes `assertions.txt` and `assertions.json`
when the checks can be evaluated. Exit 0 means all passed, 1 means an
expectation failed, and 2 means the assertion input could not be evaluated.

Pass `--assertions path/to/checks.json` to `setup/runner.py run`, or
apply the suite to an existing recording:

```sh
python3 setup/assertions.py --recording path/to/recording.csv \
  --checks tests/encoder_fault/checks.json --output setup/out/fault-assertions
```

## Demonstration

With the pinned tools installed and Matplotlib available in Python, run:

```sh
python3 tests/encoder_fault/demo.py --output setup/out/encoder-demo
```

Open `encoder-comparison.png` in the output directory or view the
[retained comparison](evidence/encoder-fault-comparison.png). Load the
baseline and faulted CSVs separately in the replay viewer. The demo runs
the same ELF twice and expects the runner to exit 0 for baseline and 1
for faulted. An unexpected exit fails the demonstration. It leaves both
recordings, readable and JSON results, and an exit-status summary.

From 1.1 to 1.9 s, baseline right A delivered all 2,601 physical edges,
with 0.033 rad/s of tracking error. The stuck-low run produced 8,359
physical edges and zero delivered edges. Its tracking error rose to
22.0 rad/s as the firmware estimated near-zero speed and commanded more
drive. After clear, the estimated wheel speed recovered promptly, while
the physical wheel took time to slow. The comparison saw 7.32 A peak
model current magnitude and 190 ms at or above 99% duty, primarily in
the response after clearing. At that same time the example firmware
changes its speed reference to zero in both runs, so this comparison
does not isolate that braking transient from the reference change. At 3 s, the faulted run still showed 35,331 signed physical right-wheel
counts and 14,436 cumulative firmware right-wheel counts. A successful
motion demo would not expose this mismatch between real shaft motion
and the controller's feedback. These checks report that mismatch
externally. They provide no evidence that the MCU firmware detected it.
The limits in the example suite characterize this demo and are not
physical safety limits. See the [retained assertion results](evidence/encoder-fault-results.json).

The [separate recovery experiment](encoder-recovery.md) clears the fault
while the firmware still commands a constant speed. The original
demonstration above remains available.

## Regression checks

Run the focused live and scheduled fault checks with:

```sh
python3 tests/encoder_fault/live_fault_check.py --output setup/out/fault-check
```

This verifies a paused high fault on left B, a simultaneous load, clearing,
reset with a queued command, timer-grid scheduling, and byte-identical
reproduction of the saved version 2 CSV and event log. The Chromium smoke
test in `tests/encoder_fault/browser.mjs` accepts a setup URL and a local
Chromium CDP URL. It exercises the real control labels, the passive-profile
exclusion, pause and resume, clearing, and the replay readout.
