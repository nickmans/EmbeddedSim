# EmbeddedSim

Embedded robotics simulator with a headless planar differential-drive robot:
compiled STM32 firmware controls two torque-driven wheels through real PWM,
direction GPIO and independent encoder timers. Physical values are illustrative;
the model has not been validated against physical hardware.

Start with the [external tester guide](docs/external-tester.md) for a clean Linux
checkout and first run. See the [performance report](docs/performance.md)
for measured execution, browser traffic, and command latency.

Use the [local robot setup](setup/README.md) to supply an STM32 ELF, discover
qualified pins, connect the differential-drive preset, and run a scenario for
replay. Start it with `bash setup/start.sh`. The same interface supports
[live simulation](docs/live-simulation.md) with pause, resume, and a recorded
right-wheel load change.

See [encoder fault scenarios and assertions](docs/encoder-faults.md) for a
reproducible feedback-loss demonstration.

The [STM32CubeF4 HAL compatibility report](docs/cubef4-hal-compatibility.md)
covers a handwritten external-ELF fixture built with ST startup, CMSIS and
HAL, and records the remaining CubeMX/CubeIDE qualification. The
[third-party PWM qualification](docs/third-party-pwm-qualification.md) tests
the original committed ELF from a public STM32F407 project on a signal bench.

Build firmware, qualify added pins/timers, run the robot, export trajectory
and telemetry, and run all existing motor/peripheral/GDB regressions:

```sh
bash tests/robot/check.sh
```

See [robot equations, hardware profile and results](docs/robot.md).
Robot CSV/PNG/JSON are in `tests/robot/out/`. The original single-motor
demonstration below remains runnable with its original hardware profile.

Generate the main recording and serve the [2D replay viewer](viewer/README.md)
with `bash viewer/demo.sh`. Open http://127.0.0.1:8765/viewer/ to inspect the
trajectory and telemetry or load another local robot CSV.

Build firmware, run all motor scenarios, export plots/traces, and rerun the
peripheral and GDB checks:

```sh
bash tests/closed_loop/check.sh
```

See [motor-loop results and timing contract](docs/motor-loop.md).
Generated CSV/PNG/JSON are in `tests/closed_loop/out/`; the report retains
the load-response plot and measured results for review.

Run the patched firmware regression suite and original smoke/GDB checks:

```sh
bash tests/peripherals/check.sh
```

See [peripheral qualification](docs/peripheral-qualification.md) for the exact
pins/clocks, 57 checks, patch architecture, baseline failures and limitations.
The reproducible source patches and platform are in `emulation/renode/`.
The command installs pinned local tools when absent; no Renode SDK build is
required. Stock comparison: `python3 tests/peripherals/run.py --stock`
(deliberately returns nonzero).

See [feasibility and implementation path](docs/feasibility.md) for the
recommended STM32F407VGT6/Renode target, tested capabilities, known peripheral
limitations, proposed structure and next coding milestone.

The historical [diagnostic experiment](experiments/renode-smoke/) compiles
and executes real Arm firmware. From `/workspace/EmbeddedSim`:

```sh
bash experiments/renode-smoke/bootstrap.sh
python3 experiments/renode-smoke/verify.py
python3 experiments/renode-smoke/gdb_check.py
python3 experiments/renode-smoke/limitations.py
```

These commands default to stock Renode. The last confirms two stock emulator
limitations; it is not a conformance pass. The combined command above sets
`RENODE_QUALIFIED=1` when rerunning them against the fixes.
All generated output is ignored under `out/`.
Use the existing isolated checkout; no worktree is needed.
