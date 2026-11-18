# Live robot simulation

## Launch and use

Run from the repository root.

```sh
bash setup/start.sh --port 8771
```

Open `http://127.0.0.1:8771/setup/` in a browser on the server machine.
For a remote checkout, forward port 8771 over your SSH connection or
open a browser on the server. The HTTP server binds to IPv4 loopback.

1. Select **STM32F407VGT6 · HSI16 robot**, choose a compatible ELF or
   select **Use example ELF**, and configure the existing differential-drive
   scenario. Enable the example observer only for compatible firmware.
2. Choose **Prepare live simulation**. When the viewer reports **Ready**,
   click **Start**. The scene shows the latest ground truth and, when
   available, firmware odometry and estimates.
3. Click **Pause** and wait for **Paused**. Enter an external right-wheel
   viscous resistance from 0 through 0.02 N·m/(rad/s), choose **Queue load**,
   then **Resume**. The viewer shows the virtual application time. The
   control changes resistance at the wheel. Firmware responds through its
   normal encoder feedback path.
4. **Stop** archives the available samples. **Reset** archives the running
   generation, creates a fresh Renode machine with the original ELF and
   configuration, and returns to **Ready**. Each run has a distinct
   recording ID.
5. At **Stopped** or **Completed**, use **Save CSV**, **Save events** and
   **Save config**, or select **Open recorded replay** to use the historical
   scrubber. **Run for replay** in setup remains available for offline runs.

The passive PLL168 firmware profile exposes pin discovery and hides the
robot wiring and execution controls. Its API rejects robot simulation.

## Session states and timing

| State | Behavior |
| --- | --- |
| Preparing | The worker configures a new machine and loads verified ELF segments. |
| Ready | Firmware and physics are at virtual time zero. Start releases execution. |
| Running | Renode advances the MCU and physics together in slices of at most 100 ms virtual time. |
| Paused | The worker waits at a completed slice boundary. Polling and rendering do not advance either clock. Resume uses the same process and machine state. |
| Completed | The configured duration was reached and the recording was finalized. |
| Stopped | A stop took effect at a boundary. A run stopped before its first sample has only configuration and event metadata. |
| Failed | The worker releases the emulator and reports the failure. Reset can prepare a fresh machine. |

One server worker writes commands to a private Renode stdin pipe and
checks each completion response. HTTP handlers submit controls and read
snapshots. The worker owns the Renode process and closes it before a
reset or terminal state releases the execution slot. Offline jobs share
that slot. One control and one load change may wait at a time. An
in-flight slice finishes before a pause, stop or reset takes effect.
A button click disables conflicting controls immediately while the request is sent.
An HTTP acceptance means the request is queued. A state change confirms the
worker reached a boundary, while the load event carries its precise application
time. Reset stays in Preparing while a fresh machine boots. Browser status
visibility also depends on the presentation poll interval.
The configured end can shorten the last slice. The existing integration
step and 1 ms recording schedule remain in force.

A running load command applies at the next available slice boundary.
A paused command remains pending until resume. An acknowledged event
changes the right resistance for the interval following its timestamp and
overrides the right side of any later configured load events for that run.
Left-side loads still follow the scenario. The sample ending at the
boundary describes the preceding interval. Stops and resets discard a
load still pending. The applied event log contains its sequence, virtual
nanoseconds, coefficient, ELF hash and initial configuration hash.

The [encoder fault controls](encoder-faults.md) use the same boundary
mechanism. Fault-enabled sessions use event log version 2 and record both
physical and delivered encoder activity.

The server records full-resolution rows as each slice ends. A run is
limited to 30 s and 30,000 samples. The browser sees a bounded
presentation history at 20 ms sample spacing plus the latest sample.
It polls at roughly four requests per wall second with one request in
flight, sends only newly accumulated presentation rows after its cursor, and
displays the latest
received pose. A slow viewer can skip presentation updates and catch
up on its next poll. On reset or reconnect with a fresh tab the viewer
can request a bounded snapshot of the current generation. The recording timestamps always come from Renode.
The wall clock includes pauses, and the speed readout divides virtual
time by the wall time spent executing and capturing slices.

Closing the tab or losing the connection leaves the machine in its
current execution state. Running sessions continue to their configured
end, and paused or ready sessions wait. Reopen the live link or use
**Open live session** in setup. The server retains only the current live
session in memory. Prior finalized recordings remain on disk in
`setup/out/jobs/<recording-id>/` or the configured artifact directory. Server shutdown closes the live Renode
process. Keep the downloaded artifacts for later replay or reproduction.

## Headless reproduction and verification

Reproduction takes the original ELF, saved configuration, and ordered
event log. The CLI checks both input hashes and applies the same virtual
boundaries through the same engine.

```sh
python3 setup/live.py --elf path/to/original.elf --config path/to/config.json \
  --events path/to/events.json --output setup/out/live-reproduction
```

Retain the uploaded ELF. For the example button, the original example
was rebuilt byte-identically in this checkout with
`python3 setup/runner.py build-example --output setup/out/example-rebuild.elf`.
Rebuilding from a different checkout or toolchain can change the hash.

```sh
python3 tests/setup/live_check.py --output setup/out/live-verification
```

The loopback API test verified movement, stationary pause, a pending load,
resume on the same Renode process, stop, and two fresh resets. It also
verified execution without browser polling, rejection of a competing
offline job, completion with an uploaded telemetry-free fixture, and
rejection of the passive profile. Headless reproduction of the stopped
recording was **byte-identical** on the pinned toolchain.

The test applied 0.012 N·m/(rad/s) at **1.100 s** virtual time. It recorded
2,200 samples through 2.200 s. The first sample reflecting the load was
1.101 s. Against the identical no-load run, the mean right speed changed
by −3.35 rad/s in the 60–200 ms after the event. Right current rose by
1.32 A and firmware-driven PWM duty by 20.20 percentage points in the
250–550 ms after the event. The API test achieved **0.57×** average
execution speed, with 4.58 s wall elapsed for 2.20 s virtual time
including the pause. See the [measured results](evidence/live-results.json).
The headless Chromium screenshot during concurrent
checks showed about **0.31×**. These are measurements of this environment.

Headless Chromium exercised setup, live movement, pause, queuing a load,
resume, a network disconnect and reconnect, stop, downloading CSV bytes,
and opening the recording in the separate scrub-capable replay viewer.

The existing setup and replay suites passed (five and six tests). The
robot, motor, peripheral, firmware smoke, GDB, time-base and CubeF4 HAL
qualifications also passed. All seven retained robot and physics CSV
hashes matched.

## Limits

The supported robot, MCU, wiring, physics and telemetry scope are the same
as in offline runs. Live input supports right-wheel viscous resistance and opt-in digital encoder faults.
The server maintains a single execution slot, and controls take effect at
slice boundaries. Live presentation is sampled and execution speed varies
with workload. Physical accuracy and MCU cycle accuracy remain unmeasured.
