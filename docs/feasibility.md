# EmbeddedSim feasibility assessment

Historical assessment. The subsequent [peripheral qualification](peripheral-qualification.md)
reproduces these findings, supplies source patches and records the tested scope.

Assessed 17 November 2026. **Recommend Renode 1.17.0 with STM32F407VGT6
(STM32F4 Discovery class) as the first exact target.** Reuse its Cortex-M4 CPU,
NVIC, bus and timer models. The basic signal paths work with compiled firmware;
the stock platform is not yet a faithful F407 peripheral implementation.
Qualify and repair a narrow timer/clock slice before building the motor loop.

## Environment and reproducibility

The existing `/workspace/EmbeddedSim` checkout was empty, on unborn branch
`work`, with no commits, files, local AGENTS.md, dependency manifests or CI.
No existing work was overwritten. GitHub Git reads succeeded, but the remote
advertised neither HEAD nor main. No commits or pushes were made.

Host: Debian 13.6, x86-64, 5 logical CPUs, 33 GiB RAM, about 60 GiB free.
Initially available: host GCC, Python 3.12, Git, curl, tar, dpkg tools.
Initially absent from PATH: Arm GCC/GDB, Renode, Mono/.NET SDK, Clang,
CMake and Ninja. The supported system-package helper was absent.

Installed locally outside the application checkout:

- `/workspace/tools/renode_1.17.0-portable`: official self-contained Linux
  release; reports `1.17.0+20260907gitf1dd1b4af`, .NET 8.0.12. No system
  Mono/.NET installation needed to run this release. Building modified Renode
  source still requires an SDK/build workflow; that was not tested.
- `/workspace/tools/xpack-arm-none-eabi-gcc-15.2.1-1.1`: existing GNU Arm
  compiler 15.2.1 and GDB 16.3.90. Compiler archive matched the publisher's
  SHA-256 file. Renode's release archive was downloaded over verified HTTPS;
  its locally recorded hash is pinned in the bootstrap, not represented as a
  publisher signature or independent checksum.
- Source inspections: Renode tag `v1.17.0`, commit
  `ab721d88e135a1bcb8ed2ecc5a38f51cbe61fdd2`; its infrastructure submodule
  `066a7f13c052215632d469c995c89aea37c573b1`. Release binary build suffix and
  tag commit differ; runtime findings below refer to the named binary and
  source findings to these pinned sources.

Reproduce from `/workspace/EmbeddedSim`:

```sh
bash experiments/renode-smoke/bootstrap.sh
python3 experiments/renode-smoke/verify.py
python3 experiments/renode-smoke/gdb_check.py
python3 experiments/renode-smoke/limitations.py
```

All four commands were executed successfully. Bootstrap was exercised again
with retained downloads/installations; fresh-machine restoration was not tested.
Generated firmware, platform, scripts and current-run logs are in
`experiments/renode-smoke/out/` (ignored). The smoke runner asserts output as
well as exit status: Renode Monitor can report a script error and still exit 0.
GDB test uses local port 3333 and terminates its own emulator afterward.

Network limitations encountered, with workarounds:

- GitHub REST `api.github.com/.../releases/latest` returned HTTP 403; Git,
  GitHub release pages and asset downloads worked. No token was needed.
- Stock F4 platform initialization downloads
  `https://dl.antmicro.com/projects/renode/svd/STM32F40x.svd.gz`;
  the proxy rejected CONNECT with HTTP 403. The generated local platform
  omits **only** `ApplySVD`, which supplies register annotations, not peripheral
  behavior. Existing upstream register tags remain. No firmware access to
  those tagged addresses is used here. Upstream tests needing downloadable
  ELF files from that host were not run. Allow `dl.antmicro.com` to run those
  unmodified tests; no network settings were changed during this assessment.
- Default Renode config initialization failed on read-only
  `/home/agent/.config/renode`; `XDG_CONFIG_HOME=/workspace/.runtime-config`
  fixes it without changing HOME or the sandbox.

## Capability evidence

“Runtime verified” means the included experiment ran here. Source inspection
and upstream tests are evidence of implementation/intent, not tests run here.

| Requirement | Evidence and limits |
|---|---|
| ELF loading and boot | **Runtime verified.** GNU Arm GCC compiled freestanding Thumb Cortex-M4 code, linked at `0x08000000`. `sysbus LoadELF` loaded 436 bytes, used vector-table SP `0x20020000` and reset PC `0x080000D5`. Firmware wrote RAM marker `0xC0DEF407`. No scripted replacement for firmware. This does not validate arbitrary HAL/RTOS/FPU firmware or bootloader/remap behavior. |
| RCC configuration | **Partial; runtime-confirmed limitation.** Stock timer clocks are fixed at 10 MHz, SysTick at 72 MHz [1]. Our explicit HSI profile uses 16 MHz, matching reset HSI; firmware enables the required RCC bits normally. Changing APB1 to /4 left PWM unchanged, although F407 timer clock should become 8 MHz and period about 2 ms. RCC ready/status flags are modeled, but most clock/prescaler/enable registers do not affect peripherals; the source explicitly says so [2]. PLL startup and a real 168 MHz Cube/HAL boot were **not tested**. |
| GPIO and alternate functions | **Runtime verified for selected pins.** Firmware selects PA0 AF1; TIM2_CH1 reaches an external C# `IGPIOReceiver` through the GPIO model. Host A/B stimuli enter PA6/PA7 and reach TIM3. Platform wiring and GPIO output AF selection exist [1,3]. Input `OnGPIO` forwards signals without equivalent AF-selection checks [3]; complete pin-mux correctness is not established. |
| Observable PWM | **Runtime verified**, TIM2_CH1, edge-aligned PWM1, PSC=15, ARR=999, CCR1=250. External observer saw 10 rising/9 falling edges in the first 10 ms; steady period **999 us**, high time **250 us**, approximately 25% duty. Expected hardware period is 1000 us: a one-counter-tick discrepancy remains, so the smoke test allows 2 us. Connections, PWM transitions and compare timer callbacks are implemented [4]. Duty updates, 0/100%, preload boundaries, inversion and center-aligned behavior remain untested. |
| Quadrature into timer encoder mode | **Runtime verified for mode 3 and one sequence each direction.** Firmware configures TIM3 input channels and SMS=3. Injecting A↑ B↑ A↓ B↓ makes firmware read CNT=4; reverse order returns it to 0. Driver never writes CNT. `HandleEncoderMode` implements edge-driven increments/decrements [4]. **Confirmed defect:** after clearing CEN, another A edge still produces CNT=1. Handler lacks an enable check. Input filtering, polarity, DIR updates, wrap/underflow, encoder modes 1/2 and overflow interrupts need qualification; this small sequence does not prove them. |
| Timer interrupts | **Runtime verified**, TIM4 update → NVIC IRQ30 → firmware ISR, clearing SR and incrementing RAM counter 10 times in 10 ms. ISR breakpoint also hit in GDB. Source aggregates update/capture/trigger IRQs [4]. Break/commutation IRQs are forced false; do not claim advanced-timer interrupt completeness. Capture IRQ and encoder overflow IRQ were not tested. |
| Simulation time | **Runtime verified.** Paused `emulation RunFor` calls advanced 10+1+1 ms; reported virtual time exactly `0.012000000`. `RunFor` starts, advances and pauses the emulation [5]. `Machine.ScheduleAction` exists for timed component work [6], but a motor's synchronized event scheduling was not implemented or tested. No real-time throughput or cycle-accuracy claim. |
| GDB | **Runtime verified.** GNU Arm GDB connected to Renode's server, broke in `tim4`, read RAM marker and PC, single-stepped, detached [6]. First attempt used `StartGdbServer ... false` and timed out because emulation was not started; enabling autostart fixed it. Hardware watchpoints, multicore and reverse debugging were not tested. |

The encoder smoke injects its four edges while paused, at one virtual instant;
it verifies routing/counting and subsequent firmware reads, not edge timing,
filtering or scheduler coupling. A timestamped encoder source remains future work.

Upstream's F4 Discovery tests contain PWM capture, four-channel capture,
quadrature position and Zephyr boot cases [7]. These substantiate intended
use but were **not executed here**. We did not run a motor, speed controller,
robot physics, HAL initialization suite or GUI.

## Recommended integration

Keep **STM32F407VGT6**, rather than changing chip solely for apparent board
coverage. The tested timer paths already address the required loop. Use
TIM2_CH1 / PA0 AF1 for PWM, TIM3_CH1/CH2 / PA6/PA7 AF2 for encoder inputs,
and TIM4 update interrupts for the speed-control tick. These are general
purpose timers, avoiding advanced TIM1/TIM8 dead-time/break complexity.

Create a device-specific platform: 1 MiB flash, 128 KiB main SRAM and 64 KiB
CCM SRAM, correct peripheral/pin inventory, HSI=16 MHz and board HSE=8 MHz.
The smoke uses the generic F4 map, which is broader (2 MiB flash/256 KiB SRAM)
and is **not** an exact memory-map qualification of this package.

Required emulator work, not firmware workarounds:

1. Repair encoder CEN handling; test direction, ARR wrap and channel gating.
   Review GPIO input routing so disabled/wrong alternate functions cannot
   silently drive the encoder. Implement the subset needed by the reference
   firmware and make unsupported settings visible.
2. Connect RCC-derived APB timer frequencies and enable/reset semantics to
   TIM2/3/4 and SysTick, including APB timer doubling. Start with HSI and one
   explicit HSE/PLL168 configuration; do not advertise arbitrary clock trees.
   Fixed platform frequencies are useful diagnostics, not a substitute for
   RCC support in arbitrary loaded firmware.
3. Resolve the ARR period discrepancy and qualify CCR preload/update events,
   PWM duty limits, stop/start and required encoder overflow semantics.
   Digital filters can be deferred for ideal encoder signals, but must be
   explicitly unsupported until modeled, not silently called functional.

Implement component adapters as C# Renode peripherals with timestamped GPIO
connections and virtual-time scheduling. Keep the motor equations in an
emulator-independent library; start with current and shaft speed/position:
`L di/dt = V - R i - Ke omega`,
`J domega/dt = Kt i - b omega - load`, `dtheta/dt = omega`.
Represent driver supply, enable and direction explicitly; PWM alone does not
define motor voltage polarity. An averaged-voltage motor is acceptable for
speed-control scope if duty is measured from actual PWM edges and the omitted
switching/current ripple is documented. Use small deterministic integration
steps, then prove timestep convergence; do not choose a universal step blindly.

Encoder model converts simulated angle crossings to ordered A/B transitions
and sends them through MCU GPIO/timer inputs. Never write TIM3 CNT or replace
the firmware controller with host logic. Firmware owns register configuration,
encoder reads and duty updates. Schedule edges at virtual timestamps; wall
clock sleeps or unordered RPC calls must not define the physics clock.
Use Python only for orchestration, assertions and result export initially.
In-process coupling minimizes causality/IPC issues; validate synchronization
quantum and event ordering before considering an external physics process.

## Focused alternative checked

QEMU source at `97c88c61d45dee6e1f9bc160a338048189846d28` has an
STM32F405 SoC, but its GPIOA–I are `create_unimplemented_device` placeholders
[8]. Its F2xx timer stores SMCR without decoding encoder mode, exposes only
an IRQ, and prints a PWM duty debug message rather than emitting PWM channel
signals [9]. This is a **source-only investigation**, not a QEMU runtime test
or a claim about every QEMU fork/STM32 family. It needs more peripheral work
for this specific F4 loop than Renode. Use QEMU as a fallback if Renode timing
or extension constraints prove blocking; do not write a custom CPU emulator.

## Proposed structure (not created as an application)

```text
docs/                       feasibility, scope, timing contract
experiments/renode-smoke/    this reproducible diagnostic only
firmware/                   real MCU controller, startup, linker, toolchain pins
emulation/renode/            pinned dependency/patches, F407 platform, run scripts
integration/renode/          PWM sink, driver adapter, encoder source, scheduler
models/                     pure DC motor, driver, encoder, later robot physics
tests/peripherals/          register/signal behavior with compiled firmware
tests/closed_loop/          speed steps, load disturbance, repeatability traces
tools/                      headless runner and trace conversion
presentation/               deferred; consumes traces/state, owns no simulation
```

## Smallest next coding task and acceptance criteria

**Qualify and repair one F407 timer slice before adding motor physics.**
Retain this ELF smoke, add firmware-driven clock/enable/duty transitions, and
fix only the selected timer/RCC/pin-routing behavior. Acceptance:

- Existing boot, firmware ISR, GDB and bidirectional encoder checks still pass.
- CEN=0 freezes encoder count; enabled forward/reverse edge sequences count
  exactly, with correct ARR wrap. Wrong AF/disconnected inputs do not count.
- HSI16 and HSE8→PLL168/APB1÷4 produce calculated TIM2/TIM4 rates; changing
  prescalers changes rates without host rewriting timer frequency properties.
- PWM 25%→75%, 0% and 100%, stop/restart, and CCR preload boundary behavior
  agree with the scoped hardware contract. Period matches `(PSC+1)(ARR+1)`
  within one timer tick; ISR count matches elapsed virtual time/boundaries.
- Two fresh runs yield the same event trace for the same ELF and stimuli;
  tests fail on unexpected/unimplemented peripheral accesses. Host test writes
  used for fault diagnosis are not used to make the firmware workflow pass.

Then implement the first physical milestone: **one firmware-controlled motor
speed loop**, no robot body or GUI. Acceptance should require real ELF control
of PWM; angle-derived A/B edges; firmware reading TIM3; 0→positive speed step
within 5% steady error under declared motor parameters; recovery after a load
step without saturation/instability; deterministic replay; and convergence
when the physics timestep is halved. Those are proposed tests, not achieved
results. Physical parameter choices and settling-time limits remain to be set.

Remaining risks: timer mode fidelity and boundary cases; RCC coverage; HAL
startup/FPU/interrupt-priority compatibility; scheduler quantum and ordering;
motor numerical stiffness; encoder edge density; and emulator throughput.
Instruction/MIPS scheduling is not evidence of Cortex-M4 cycle accuracy.
No application or environment configuration was published, and no full
closed-loop functionality is claimed.

## Pinned sources

1. [F4 platform: CPU, memory, clocks, IRQs and AF wiring](https://github.com/renode/renode/blob/ab721d88e135a1bcb8ed2ecc5a38f51cbe61fdd2/platforms/cpus/stm32f4.repl)
2. [STM32F4_RCC.cs, especially constructor comments and CR/CFGR fields](https://github.com/renode/renode-infrastructure/blob/066a7f13c052215632d469c995c89aea37c573b1/src/Emulator/Peripherals/Peripherals/Miscellaneous/STM32F4_RCC.cs#L22)
3. [STM32_GPIOPort.cs: OnGPIO, ChangeMode, GPIOAlternateFunction](https://github.com/renode/renode-infrastructure/blob/066a7f13c052215632d469c995c89aea37c573b1/src/Emulator/Peripherals/Peripherals/GPIOPort/STM32_GPIOPort.cs#L108)
4. [STM32_Timer.cs: PWM callbacks, OnGPIO, HandleEncoderMode, UpdateInterrupts](https://github.com/renode/renode-infrastructure/blob/066a7f13c052215632d469c995c89aea37c573b1/src/Emulator/Peripherals/Peripherals/Timers/STM32_Timer.cs)
5. [Emulation.cs: RunUntil / RunFor](https://github.com/renode/renode-infrastructure/blob/066a7f13c052215632d469c995c89aea37c573b1/src/Emulator/Main/Core/Emulation.cs#L124)
6. [Machine.cs: StartGdbServer and ScheduleAction](https://github.com/renode/renode-infrastructure/blob/066a7f13c052215632d469c995c89aea37c573b1/src/Emulator/Main/Core/Machine.cs)
7. [Upstream F4 Discovery tests, not run here](https://github.com/renode/renode/blob/ab721d88e135a1bcb8ed2ecc5a38f51cbe61fdd2/tests/platforms/STM32F4_Discovery.robot)
8. [QEMU STM32F405 SoC](https://github.com/qemu/qemu/blob/97c88c61d45dee6e1f9bc160a338048189846d28/hw/arm/stm32f405_soc.c)
9. [QEMU STM32F2xx timer](https://github.com/qemu/qemu/blob/97c88c61d45dee6e1f9bc160a338048189846d28/hw/timer/stm32f2xx_timer.c)
