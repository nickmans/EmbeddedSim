# EmbeddedSim

Embedded robotics simulator with a headless planar differential-drive robot:
compiled STM32 firmware controls two torque-driven wheels through real PWM,
direction GPIO and independent encoder timers. Physical values are illustrative;
no hardware validation or GUI is claimed.

Build firmware, qualify added pins/timers, run the robot, export trajectory
and telemetry, and run all existing motor/peripheral/GDB regressions:

```sh
bash tests/robot/check.sh
```

See [robot equations, hardware profile and results](docs/robot.md).
Robot CSV/PNG/JSON are in `tests/robot/out/`. The original single-motor
demonstration below remains runnable with its original hardware profile.

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
