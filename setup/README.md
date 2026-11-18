# Configure, discover, run and replay

See the [external tester guide](../docs/external-tester.md) for clean Linux
installation, cache and artifact overrides, and the first-run checklist.
From the repository root, start the local setup interface.

```sh
bash setup/start.sh
```

Open [http://127.0.0.1:8767/setup/](http://127.0.0.1:8767/setup/) in a browser on
the machine running the command. The server binds to IPv4 loopback. In a remote
environment, use a browser on that machine or an existing SSH connection with
local port forwarding (for example, add `-L 8767:127.0.0.1:8767` to your SSH
command). Your computer's loopback address does not reach a remote server
directly. Use `--port` to override 8767.

1. Select **STM32F407VGT6 · HSI16** and **Choose ELF**, or use the bundled example
   button to select the locally built controller. External firmware defaults to
   **None** for the observer. Only enable the example observer for firmware
   implementing its specific two-bank layout and frame signature.
2. Start with the preset wiring or disconnect endpoints before **Discover pins**.
   For encoders, connect/disconnect both phases together. Run discovery again
   after changing connections if startup depends on a device. Step through the
   snapshots to inspect register changes and measured output.
3. Choose physical connections in the wiring table. **Use confirmed preset routes**
   fills only empty slots confirmed in the selected snapshot. Manual assignment
   works before discovery. The profile and wiring validator report unsupported
   routes and duplicates without changing the selected pins. An unconfirmed
   snapshot can still be followed by a run when firmware initializes later.
4. Set duration and body parameters. The expandable scenario section includes the
   initial pose and optional external loads. **Export JSON** saves configuration
   without firmware bytes. Keep the exact ELF to reproduce a scenario.
5. **Run for replay** starts a fresh machine, with reset-state clocks, firmware
   and physics. **Open recorded replay** appears when the run finishes. Recording
   files, the validated configuration, the ELF hash, and Renode log are retained
   under `setup/out/jobs/<id>/`. Only one browser job runs at a time. Each job owns
   its inputs, temporary emulator platform, and output. The server exposes only
   the setup/replay assets and designated job files.
6. For an interactive run, choose **Prepare live simulation**. The live
   viewer starts at a fresh machine and supports execution controls, queued
   right-wheel resistance, and saving the recording. See the
   [live simulation guide](../docs/live-simulation.md).

## Command line

```sh
bash experiments/renode-smoke/bootstrap.sh
python3 setup/runner.py build-example --output setup/out/example.elf
python3 setup/runner.py discover --config setup/default.json \
  --elf setup/out/example.elf --output setup/out/discovery --seconds 0.5
python3 setup/runner.py run --config setup/default.json \
  --elf setup/out/example.elf --output setup/out/scenario
```

Substitute a separately built ELF and your saved JSON. Use new output paths.
Replay any successful `recording.csv` using **Open CSV** in the replay viewer.
For the qualified third-party STM32F407 PWM capture firmware, use
`setup/pwm-signal.json` with the same `discover` command. The
`pwm-signal-pll168-v1` profile inspects the 168 MHz clock tree, TIM2 capture
inputs, TIM3 PWM outputs, and direction/brake GPIOs. It supports passive
discovery from the CLI and rejects robot wiring or simulation runs.
See the [external ELF time-base report](../docs/stm32f407-timebase.md).

Discovery returns `result.json` with five snapshots including reset, plus the
validated config and emulator log. The run returns its own recording and
`result.json` with the ELF SHA-256. The default CLI config leaves the observer off.
To include example odometry, set `scenario.observer` to `example-v1` for the
example controller. Firmware-side geometry is compiled into that controller.
Changing the model dimensions leaves its odometry calibration as compiled.

## Version 1 configuration

[default.json](default.json) is the complete version 1 example. Fields use SI
units as indicated by the key suffixes.

| Object | Contents |
| --- | --- |
| `version` | Integer 1. |
| `target` | Explicit `part: stm32f407vgt6` and `profile: robot-hsi16-v1`. |
| `robot` | The `differential-drive-v1` preset describes mass, yaw inertia, wheel radius, track and wheel inertia, along with two identical direct-drive motors, averaged drivers, and 4096-count quadrature encoders. Motor, bridge and encoder values are fixed in v1. |
| `world` | Separate `empty-flat-floor` selection, with no obstacles or collisions. |
| `wiring` | Endpoint-to-pin map. Eight connections are required to run. A discovery job can leave PWM or direction inputs or complete encoder pairs disconnected. |
| `scenario` | Duration (0.01–30 s), initial x/y/heading, optional observer, and ordered nonoverlapping viscous load events. The robot starts at rest with zero motor current. |
| `scenario.loads[]` | `start_s` inclusive and `end_s` exclusive within the scenario. `left_Nms` and `right_Nms` are additional nonnegative drag in N·m/(rad/s). Loads are applied on physics boundaries. Use an empty array for no load. |

The model uses the default 25 µs integration step and records every 1 ms. The
physical parameters are illustrative. The model assumes ideal rolling and
averaged motor electronics, and has no physical hardware validation. See the
[robot contract](../docs/robot-contract.md) for equations and signs.

Optional [encoder faults](../docs/encoder-faults.md) can be scheduled in
the scenario or applied from the live viewer when encoder evidence is enabled.

## Exact supported wiring

| Endpoints | Selectable qualified MCU routes |
| --- | --- |
| Driver PWM inputs | PA0 AF1 / TIM2_CH1 and PA1 AF1 / TIM2_CH2. Push-pull active-high PWM1, edge-aligned up, PSC=15, ARR=999 for 1 kHz with the qualified clock. |
| Driver direction inputs | PA4 and PA5 as push-pull GPIO outputs. High requests positive drive, low negative. |
| Encoder A/B outputs | PA6/PA7 AF2 / TIM3_CH1/CH2 and PB6/PB7 AF2 / TIM4_CH1/CH2. Direct TI1/TI2, SMS=3, PSC=0, ARR=65535, enabled noninverted inputs without filtering. |

Each pin can be connected once. Left and right can exchange PWM pins,
direction pins, or complete A/B pairs. The adapter does not accept A/B
cross-timer or phase reversal connections. Other routes may be valid on
hardware but are outside the qualified emulator configuration.

Discovery executes firmware for 0.01–3 virtual seconds, with a 45 s Renode
wall-clock limit. Each snapshot includes GPIO mode and AF, the qualified route,
role where identified, clock state and relevant timer registers. PWM
measurement observes pin callbacks. A full rise–fall–rise cycle supplies a
period and duty. A stable low/high output can report 0%/100% with no measured
period. The snapshot identifies stopped, unmapped, unqualified and insufficiently
observed states separately. Encoder routes report configuration with no measured
period. Changes between snapshots can be missed. The initial snapshot and an
uninitialized firmware can show all routes unconfirmed. Physical connections
remain present through register changes, subject to the existing model's GPIO
mux behavior. Arbitrary remux while signals are high is outside qualification.

## ELF startup and toolchain

The loader checks a little-endian ELF32 static ARM EABI5 executable and the
program-header table, bounds and overlap of loadable ranges. Supported memory
is Flash `0x08000000` (1 MiB), main SRAM `0x20000000` (128 KiB), and CCM
`0x10000000` (64 KiB). The image must provide a vector table at Flash base, an
8-byte-aligned stack pointer in RAM, and Thumb reset and entry addresses in
file-backed executable Flash. The loader passes validated file-backed segment
bytes to Renode at their physical load addresses and boots the Cortex-M4 from
the vector table. The reset handler handles Flash-to-RAM initialization and BSS.
See the separately built [minimal fixture](../tests/setup/minimal.c), which
exercises Flash-backed initialized data and uses no observer ABI.

An ELF header cannot establish the exact STM32 part or compatibility of its
instructions and peripherals. This profile models HSI16, AHB÷1, APB1÷1,
APB2÷2, the listed GPIO/timers, and the startup dependencies in the
[platform description](../emulation/renode/stm32f407vg-robot.repl).
It expects standalone firmware with its own startup and interrupt handlers.
Bootloaders, external memory and other pin routes, peripherals, or clock setups
are outside this workflow's qualification. The bundled controller builds for
Cortex-M4 Thumb with the soft-float ABI. A valid image can still wait for an
unavailable device or leave the robot stationary.

The [STM32CubeF4 HAL compatibility report](../docs/cubef4-hal-compatibility.md)
documents an external GCC build with ST startup and HAL, including qualified
single-precision hard-float execution in that fixture. It also records the
remaining CubeMX generation and CubeIDE build steps.

## Checks

```sh
python3 tests/setup/check.py
node --test viewer/trace.test.mjs
bash tests/robot/check.sh
```
