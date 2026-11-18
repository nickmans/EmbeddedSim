# Encoder recovery under an unchanged command

This separate scenario uses the stock example ELF. Its right-wheel reference
is 10 rad/s from 0.2 to 2.0 s. The recording ends at 2.7 s, before the next
drive command. Baseline and faulted configurations both enable encoder
evidence and omit external loads. The faulted configuration adds only a
right A stuck-low interval from 0.950 to 1.200 s.

## Evaluation plan

The thresholds and phase meanings were chosen before running either case.
A baseline-only calibration with an earlier fault schedule measured
0.778 rad/s at 0.700–0.800 s, above the predeclared 0.6 rad/s limit.
The harness stopped before running the faulted case. The normal window
and fault interval were then moved 150 ms later, preserving the thresholds
and durations. The windows below were fixed before the first faulted run.
Limits characterize the example response in simulation. Current and duty
are descriptive measurements under the idealized averaged driver and motor
parameters.

| Window | Virtual time | Evaluation |
| --- | --- | --- |
| Normal tracking | 0.850–0.950 s | Mean absolute error (MAE) ≤ 0.6 rad/s. A 6% band allows ordinary startup settling and encoder quantization. |
| Fault interior | 1.000–1.175 s | Tracking expectation MAE ≤ 2 rad/s and ≥ 200 GPIO edges if the shaft produces ≥ 200 physical edges. A 10 rad/s wheel should produce about 570 A edges in this window. Both checks deliberately use healthy feedback expectations. |
| Immediate reconnection | 1.200–1.300 s | Report encoder activity, actual and estimated speed, signed PWM and model current. This window spans five 20 ms firmware speed-estimation windows. |
| Continued unchanged command | 1.650–1.900 s | MAE ≤ 1 rad/s as an explicit 10% regained-tracking criterion. Report the cumulative count and odometry discrepancy separately. |
| Commanded stop | 2.050–2.650 s | Report separate stop response under the zero reference. |

An expected failed assertion has exit status 1 **and** a written assertion
summary with the expected failures. The experiment harness treats a missing
summary, unexpected failure outside the observational recovery check, or an incorrect exit status as a test
failure.

## Run and reproduce

With the pinned tools and Matplotlib available, run from the repository root:

```sh
python3 tests/encoder_fault/recovery.py --output setup/out/encoder-recovery
```

Use a new directory for each run. The command retains the exact ELF, both
configurations, authoritative CSVs, text and JSON assertion reports, a plot,
and window-by-window metrics. Open either CSV in the replay viewer. To repeat
just one case with the saved configuration and exact firmware:

```sh
python3 setup/runner.py run \
  --elf setup/out/encoder-recovery/example.elf \
  --config setup/out/encoder-recovery/faulted/config.json \
  --assertions tests/encoder_fault/recovery-checks.json \
  --output setup/out/recovery-repeat
```

A faulted exit of 1 is expected for the deliberately violated feedback
expectations. The plot shows raw speed and model current along with PWM
duty multiplied by the observed GPIO direction. The CSV preserves duty
and direction separately. Edge activity uses differences of cumulative
counts over `(start,end]`. Count gap is signed physical right quadrature
count minus the firmware's accumulated count. The small baseline gap
includes the sampling offset between the model and firmware frame. Position
error is the distance between the firmware odometry and the model's planar
position. The reported mask transition times are observed at the 1 ms
recording resolution. The configured fault boundaries align with those
samples.

## Observed result

The sample stream recorded the mask turning on at **0.950 s** and clearing
at **1.200 s**. Both runs recorded 10 rad/s from 0.201 s until the first
zero-reference sample at **2.001 s**. All recorded rows before activation
matched. The baseline passed all four assertions and exited 0. The faulted
case exited 1 with exactly the two intended healthy-feedback failures.
It passed both the pre-fault and the later tracking limits.

| Measurement | Baseline | Faulted |
| --- | ---: | ---: |
| Normal tracking MAE | 0.380 rad/s | 0.380 rad/s |
| Fault-interior tracking MAE | 0.153 rad/s | 5.387 rad/s |
| Fault-interior A edges, physical / GPIO | 562 / 562 | 879 / 0 |
| Reconnection A edges, physical / GPIO | 324 / 324 | 635 / 635 |
| Reconnection peak model current magnitude | 0.046 A | 2.562 A |
| Continued-command tracking MAE | 0.010 rad/s | 0.777 rad/s |
| Continued-command estimate vs model speed MAE | 0.038 rad/s | 0.045 rad/s |
| Count gap at 1.900 s | 7 | 2,427 |
| Planar odometry error at 1.900 s | 0.00056 m | 0.272 m |
| Planar odometry error at 2.650 s | 0.00005 m | 0.361 m |

The faulted wheel reached about 21 rad/s near reconnection. Inside the
first 100 ms after clear, the firmware estimate rose from near zero to
20.94 rad/s and the signed PWM ranged from −0.346 to +0.492 as the
controller responded under the same command. The later unchanged-command
window met the 1 rad/s tracking criterion. The accumulated count and
position errors persisted through the later commanded stop. This
demonstrates speed-loop recovery under the chosen criterion, and shows
why it is insufficient evidence of recovered odometry. The motor current
values come from the averaged driver and illustrative motor model.

[Recovery comparison plot](evidence/encoder-recovery.png) ·
[Window metrics and assertion results](evidence/encoder-recovery-results.json)
