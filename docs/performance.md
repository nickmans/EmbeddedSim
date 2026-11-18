# STM32F407 external tester performance

## Method

The benchmark uses the same example ELF in all trials, with HSI16,
the preset wiring and example-v1 observer, the default right-wheel
viscous load of 0.0015 N·m/(rad/s) from 0.8 to 1.4 seconds, 25 µs
physics, and 1 ms authoritative recording. Headless mode invokes the
same slice runner that reproduces saved live events. It uses no HTTP
server or browser. Unattended live reserves an HTTP session and starts it
with one POST, with no viewer polling. Browser mode adds a real Chromium
tab running the viewer over loopback. All three save authoritative CSV and
event JSON. The main trials never pause. Command latency and an explicit
stationary pause are checked separately.

The test machine was a shared Debian 13 x86-64 environment with an
Intel Xeon Platinum 8573C, five visible logical CPUs, a four-CPU cgroup
quota, and a 32 GiB memory limit. Renode was 1.17.0
(build `1.17.0+20260907gitf1dd1b4af`, .NET 8.0.12), xPack Arm GCC
15.2.1-1.1, Python 3.12.14, Node 24.22.1, and Chromium 156.0.8078.79.
Machine setup is cold per run while the OS and installed tool caches
are warm. Chromium runs headless with a 1440 by 1050 window setting. Parallel checks and
shared host activity can affect performance.

With dependencies bootstrapped, run:

```sh
python3 tests/performance/benchmark.py --output setup/out/perf --latency
python3 tests/performance/profile.py --elf setup/out/perf/example.elf \
  --output setup/out/profile
```

Use a new output directory each time. Use `--elf` with the exact first
run's ELF, and keep the generated JSONL for comparison. The benchmark
is two repetitions by default and reverses mode order on the second
repetition. Use `--repeats` for a longer series and `--modes` or
`--durations` for diagnosis. Node 24 and Chromium are required for the
browser mode. Set `CHROMIUM` for a custom executable. The verification
environment required the harness’s `CHROMIUM_NO_SANDBOX=1` setting for
headless Chromium. The profiling tool
instruments a scratch C# copy and accepts `--checkout` for a baseline
source tree. Its overhead makes its absolute timings unsuitable as
throughput measurements.

**Advancing speed** divides virtual run duration by time inside the
sliced advance and capture path. This includes recording collection at
the boundary. Startup, terminal cleanup, explicit pauses and browser
wall time are measured separately. In the raw JSONL, `step` includes
`advance_monitor` and `capture` and overlaps them. `capture` in turn
includes `export_monitor` and draining the slice into the artifact CSV.
`__init__` is machine startup, including model preparation, compilation
in Renode and the initial export. `finish` finalizes the authoritative
files and `close` tears down Renode. Overall `elapsed_s` includes startup
for headless mode and starts at the start request for live modes.
Browser response bytes are the sum of encoded GET bodies from Resource
Timing. CDP task, script, layout and style counters describe renderer
work and should not be added together.

## Before and after

Each cell gives the median and observed range from two runs in
**virtual seconds per advancing wall second**.

| Virtual run | Mode | Before | After |
| ---: | --- | ---: | ---: |
| 10 s | headless | 0.94 [0.94–0.94] | 0.73 [0.59–0.87] |
| 10 s | live | 0.94 [0.94–0.95] | 0.89 [0.88–0.90] |
| 10 s | browser | 0.85 [0.75–0.94] | 0.80 [0.70–0.90] |
| 30 s | headless | 0.95 [0.94–0.95] | 0.94 [0.93–0.95] |
| 30 s | live | 0.95 [0.95–0.96] | 0.94 [0.93–0.95] |
| 30 s | browser | 0.91 [0.89–0.94] | 0.89 [0.84–0.94] |

The wall-clock comparison varied with shared-host load. The interrupted
attempt overlapped multiple regression suites. Its 30 s headless run ran
at 0.37×, and a 30 s live run exceeded the initial 150 s harness wait.
The repeated after series used a 300 s wait. The faster runs and the
contended attempt are both retained. These measurements do not establish
an emulator throughput gain.

The example ELF compiled in 0.165 s once before the trials. The after
series reused the same image. The table below gives medians and ranges
for the six 30 s measurements in each series. It combines the three
execution modes.

| Phase (wall seconds) | Before | After |
| --- | ---: | ---: |
| Prepare machine | 11.15 [9.95–12.22] | 11.22 [10.32–14.41] |
| Advance monitor | 30.93 [30.78–32.32] | 31.11 [30.82–34.39] |
| Capture and append | 0.822 [0.623–1.569] | 0.856 [0.638–1.340] |
| Export monitor (included in capture) | 0.659 [0.473–1.184] | 0.683 [0.512–1.079] |
| Finalize files | 0.0007 [0.0005–0.0019] | 0.0007 [0.0004–0.0010] |
| Close Renode | 0.118 [0.114–0.166] | 0.116 [0.115–0.168] |

Only the browser-connected runs generate browser Resource Timing and
renderer measurements. The response totals include the small status
envelope on each poll.

| Browser metric (median and range) | Before | After |
| --- | ---: | ---: |
| 10 s response bodies (MB) | 3.965 [3.711–4.218] | 0.275 [0.272–0.279] |
| 30 s response bodies (MB) | 34.280 [30.224–38.335] | 0.732 [0.731–0.733] |
| 30 s total request duration (s) | 1.534 [1.229–1.839] | 1.209 [0.563–1.854] |
| 30 s renderer task time (s) | 5.232 [4.418–6.045] | 4.713 [2.844–6.583] |
| 30 s layout time (s) | 0.250 [0.235–0.266] | 0.303 [0.238–0.367] |

Every completed benchmark CSV and event log matched byte for byte
at its duration, regardless of mode or revision. All seven regenerated
robot and physics trace hashes matched the pre-existing retained
evidence. The live regression also reproduced the recording of a
paused, queued load byte for byte in the headless runner. See the
[raw benchmark measurements](evidence/performance-results.json).

## Profiling

A separate 3 s instrumented run used the same observer and load. Values
below are elapsed wall seconds inside each measured region. The encoder
region includes quadrature calculations and forwarding real GPIO changes.
Recorder formatting includes building the row and the trace's timer
register reads, while observer time measures the example firmware memory
reads.

| Instrumented region | Before | After |
| --- | ---: | ---: |
| Model integration | 0.239 | 0.199 |
| Encoder and GPIO | 0.712 | 0.784 |
| Driver and load bookkeeping | 0.072 | 0.074 |
| Firmware observation | 0.139 | 0.200 |
| CSV row formatting | 0.263 | 0.161 |
| Renode CSV export writes | 0.017 | 0.011 |
| Entire advance and capture | 8.354 | 6.080 |

The encoder path was the biggest individually measured section inside
the robot loop. Instrumentation leaves most wall time outside these
regions. That residual includes CPU emulation, clock and peripheral
scheduling, waits and host preemption. This environment lacks a native
sampling profile that could attribute the residual to those components.
The single instrumented runs are used for bottleneck selection only.
The benchmark's separate monitor and export timings quantify the slice
communication, and Chromium records presentation costs.

## Changes under test

- The browser requests only the presentation rows after its cursor.
  Generation changes and missed polls can recover a bounded snapshot.
  It retains one in-flight status request, receives the latest sample
  between the 20 ms display points, and continues to draw the full
  available path. The authoritative 1 ms recording is retained in full.
- Each wheel reuses its encoder callback. Call order, GPIO writes, and
  all quadrature transitions stay the same. This removes a closure and
  delegate creation for each wheel on every integration tick.
- A monitor batching experiment was abandoned after the console log
  interleaved a completion marker under load. Final measurements use
  separate advance and export acknowledgments as before.

## Command timing

The latency harness sends pause while a run is active, queues a load
while paused, resumes, stops while running, and resets the stopped
session. It polls the server state every 4 ms. HTTP acceptance represents
queuing, and settlement represents the state or load event becoming
observable at the API. The browser immediately disables conflicting
controls on click. Its ordinary poll interval is roughly 240 ms, so
visible status can lag the worker boundary. Reaching Ready after a reset
includes startup of a fresh machine. A queued paused load intentionally
waits until resume. The event's recorded `at_ns` is the virtual
application time. Browser verification also held a confirmed paused
state for 652 ms without a change in virtual time or scene.

| Observed latency (ms, median and range over three trials) | Before | After |
| --- | ---: | ---: |
| Pause accepted | 3.3 [1.5–5.3] | 2.0 [1.7–14.1] |
| Paused at boundary | 153.0 [138.2–365.4] | 150.4 [140.9–180.3] |
| Paused load accepted | 2.1 [1.8–5.6] | 1.7 [1.5–1.9] |
| Load application after resume | 6.5 [5.7–23.9] | 9.3 [5.6–10.0] |
| Stop accepted | 1.7 [1.4–2.0] | 1.7 [1.5–1.7] |
| Stop archived and closed | 267.0 [246.0–424.7] | 272.1 [265.3–341.1] |
| Reset accepted | 3.3 [2.1–5.6] | 5.4 [2.3–8.0] |
| Reset ready | 11329.4 [10443.8–12332.4] | 11946.2 [11308.4–19582.4] |

Applied events were recorded on the 100 ms virtual grid. In these trials their virtual times were 0.300 s.

## Verification

The full robot suite passed, including 22 robot hardware checks, 57
peripheral checks, motor-control scenarios, and the GDB smoke test. The
setup and replay suites passed five and six tests respectively. The live
API test covered cursor catch-up and reset, pause and queued load,
single-slot admission, and a telemetry-free external ELF. Replaying its
saved event against the baseline produced the same 2,200 CSV samples and
event JSON as the final implementation. The load was applied at 1.100 s
virtual time. The timing and third-party tests passed, including discovery
of the unchanged public ELF. Its normal result exposed flash-controller
and unsupported ITM register warnings.

A separate Git checkout with spaces in its path downloaded both pinned
archives into an empty cache, verified their hashes, and started on port
8871. Cached offline startup also worked on custom ports, including
re-extraction from verified archives into a new tool directory. Chromium
exercised example ELF selection, pin discovery with the preset wiring,
live Start, Pause, load queuing, Resume, disconnect and reconnect, Stop,
CSV download, and opening recorded replay. The API regression separately
verified fresh resets and exact replay. The empty offline cache produced
a readable missing-archive error.

## Remaining limits and next milestone

Run time varies with host load. This profile carries no promise of
real-time or cycle-accurate execution. The browser still rebuilds plots
and the trajectory from its bounded display history. Measure native
Renode execution and scheduler cost on a quieter host before changing
the timing architecture. A useful next milestone is repeating this
benchmark on a typical tester machine and profiling CPU, scheduler, and
encoder GPIO costs separately while preserving the exact trace checks.

See the [external tester guide](external-tester.md) for launch, wiring,
compatibility, and the feedback checklist.
