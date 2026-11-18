# STM32CubeF4 HAL compatibility on the robot profile

The handwritten STM32F407VGT6 fixture runs a two-wheel feedback controller
with the pinned ST HAL and CMSIS, using ST's unmodified GNU startup assembly,
Flash linker script, system initialization and newlib stubs. The emulator
loads it as external firmware with the example RAM observer disabled.

| Milestone | Outcome |
| --- | --- |
| Generate the exact project with CubeMX or CubeIDE | Blocked. Neither tool was installed, and the cloud proxy returned HTTP 403 to the connection request for both official ST download pages. There is no generated project or `.ioc` for this configuration. |
| Build the exact project with CubeIDE tooling | Blocked by tool and project availability. |
| Build the handwritten integration fixture externally | Passed with xPack Arm GCC 15.2.1. |
| Execute the resulting ELF in EmbeddedSim | Passed through the external-ELF setup workflow. |
| Physical-board validation | Untested. Results describe the supported Renode profile and virtual time. |

## Provenance

| Component | Version and source |
| --- | --- |
| STM32CubeF4 | [v1.28.3](https://github.com/STMicroelectronics/STM32CubeF4/tree/94cae6e83f00e276a11957e7833c01ac3d0bd7af) at `94cae6e83f00e276a11957e7833c01ac3d0bd7af`. The stock STM32F4-Discovery `Templates_LL/STM32CubeIDE` directory supplies startup `startup_stm32f407vgtx.s`, linker script `STM32F407VGTX_FLASH.ld`, `syscalls.c` and `sysmem.c`. The directory name identifies the target toolchain. These template files were built with external GCC. |
| STM32F4 HAL | 1.8.5 from the [CubeF4-pinned submodule](https://github.com/STMicroelectronics/stm32f4xx_hal_driver/tree/b6f0ed3829f3829eb358a2e7417d80bba1a42db7) at `b6f0ed3829f3829eb358a2e7417d80bba1a42db7`. The build compiles HAL core, Cortex, GPIO, RCC, TIM and TIMEx sources. |
| CMSIS | Core(M) header version 5.6 from the CubeF4 tree. STM32F4 device headers and `system_stm32f4xx.c` supply `SystemInit` from [device package 2.6.11](https://github.com/STMicroelectronics/cmsis_device_f4/tree/3c77349ce04c8af401454cc51f85ea9a50e34fc1) at `3c77349ce04c8af401454cc51f85ea9a50e34fc1`. |
| Compiler and emulation | xPack GNU Arm Embedded GCC 15.2.1 packaging 15.2.1-1.1, GCC build 20251203, binutils 2.45.1.20251203, Cortex-M4 Thumb-2 with `-mfpu=fpv4-sp-d16 -mfloat-abi=hard`, `-O2`, newlib-nano and nosys specs. Renode 1.17.0+20260907gitf1dd1b4af with the existing qualified patches. |
| Fixture and application | [Handwritten HAL initialization and boot checks](../firmware/cubef4-hal/main.c) and [separate application controller](../firmware/cubef4-hal/robot.c). |

The build fetches source from the official Git repositories into an external
SDK checkout. ST HAL and the Discovery template use their upstream BSD-style
licenses, and the CMSIS core and device trees carry Apache 2.0 terms. The SDK
checkout retains the original notices. This repository contains the handwritten
integration sources and measurement results. The evidence archive contains no
vendor sources or firmware binaries.

## Reproduce the external build and qualification

Run from the repository root on the supported Linux environment.

```sh
bash experiments/renode-smoke/bootstrap.sh
bash firmware/cubef4-hal/build.sh
python3 tests/cubef4-hal/check.py \
  --output firmware/cubef4-hal/out/qualification
```

The default compiler and SDK paths are under `/workspace/tools`.
`ARM_GCC` can name another compatible compiler and `STM32CUBE_F4_ROOT` can
name an unmodified Git checkout pinned to the revisions above. The build
retains the ELF and linker map in `firmware/cubef4-hal/out/`. Use a fresh
qualification output path on each run. Artifacts include discovery snapshots,
three complete recordings, validated configurations, ELF identity, logs and
a measured results summary. A second build from a clean SDK checkout produced identical file-backed load
segments. Debug sections can make whole-ELF hashes path-dependent.

The [saved scenario](../firmware/cubef4-hal/scenario.json) uses the original
wiring and body parameters, the right-wheel load from 0.8 to 1.4 s, and
`observer: none`. The integration check discovers the pins, runs the
loaded scenario twice on fresh machines, and runs an unloaded comparison
with the same ELF. Each recording is available to the replay viewer via
**Open CSV**.

To run one configuration through the same CLI used by setup:

```sh
python3 setup/runner.py discover --config firmware/cubef4-hal/scenario.json \
  --elf firmware/cubef4-hal/out/robot.elf --output setup/out/hal-discovery
python3 setup/runner.py run --config firmware/cubef4-hal/scenario.json \
  --elf firmware/cubef4-hal/out/robot.elf --output setup/out/hal-run
```

The same ELF can be selected in the local setup page using the
STM32F407VGT6 · HSI16 profile, the saved scenario, and **None** for the observer.
The qualifier invokes the same runner used by that page.

## Measured results

See the [machine-readable results](evidence/cubef4-hal-results.json).

Each run recorded 10,400 samples at 1 ms spacing. The two loaded recordings
were byte-identical despite starting on fresh machines. Both outputs first
showed nonzero PWM at 208 ms. Settled speed pairs for the straight, in-place
turn, curve and reverse phases were approximately
`(10.00, 10.12)`, `(−4.97, 5.04)`, `(6.03, 10.02)` and `(−8.01, −8.00)` rad/s.
The curve showed 2.71% left and 4.51% right mean measured duty. The turn had
opposite direction output levels. The loaded run recorded zero unsafe
direction switches.

The loaded and unloaded traces matched before 0.8 s. Right encoder count
first differed at 0.811 s and measured right PWM duty at 0.812 s.
Relative to the unloaded run, the right load increased mean duty by
3.92 percentage points and modeled current by 0.256 A in [1.10, 1.35) s.
It reduced mean modeled speed by 0.595 rad/s in [0.85, 1.10) s.
Firmware learns about the load through encoder counts. It receives neither
the modeled load nor ground-truth speed.

## Compatibility matrix

This matrix applies to the tested external fixture. The exact generated
project is still blocked and has no verified rows of its own.

| Dependency | Status | Evidence and limit |
| --- | --- | --- |
| Flash vector table and Thumb reset handler | Verified | Stock ST startup and linker produced the vector table at `0x08000000`. Setup loaded the validated segments and the firmware reached the gated start. |
| Flash-to-SRAM `.data`, `.bss`, C runtime init | Verified for fresh boot | ST reset assembly runs the copy and zero loops, calls `SystemInit` and `__libc_init_array`, then `main`. A volatile initialized value in SRAM and a zero-valued BSS probe gate the start. The BSS check uses reset RAM. Nonzero-RAM or warm-reset initialization was not exercised. |
| `SystemInit`, `HAL_Init` and RCC HAL | Verified | Start is gated on HAL success, CPACR enable and HAL clock queries. The fixture uses HSI16, HCLK 16 MHz, PCLK1 16 MHz and PCLK2 8 MHz. Discovery confirms the matching clock registers. |
| SysTick, `HAL_GetTick`, `HAL_Delay` | Verified at HSI16 | The SysTick handler uses `HAL_IncTick`. The 5 ms delay must return with 6–8 tick increments before GPIO initialization. In the bounded runs both direction outputs are first sampled high at 7 ms virtual time. Other SysTick clock rates and HAL timebases were untested. |
| NVIC and IRQ dispatch | Verified for this configuration | HAL configures priority grouping, SysTick priority 15 and TIM2 preemption priority 1. The live sequence depends on both SysTick and the TIM2 IRQ forwarding through `HAL_TIM_IRQHandler` to the period elapsed callback. General priority and preemption behavior was untested. |
| Direction and GPIO AF | Verified | PA4/PA5 are independent HAL push-pull outputs. PA0/PA1 AF1 and PA6/PA7/PB6/PB7 AF2 were confirmed by discovery. |
| TIM2 PWM | Verified | HAL configures PWM1 and starts both channels at PSC 15/ARR 999. The pin probe measures 1.000 ms on both channels. The independent duties and directions drive straight, turn, curve and reverse phases. |
| TIM3/TIM4 quadrature | Verified | HAL starts both timers in TI12 mode. Measured hardware counter registers match generated encoder counts modulo 65536 across the loaded trace. The load changes the right counter before the controller changes right duty. |
| FPv4-SP hard float | Verified for emitted single-precision instructions | ELF attributes report VFP register arguments. The stock CMSIS `SystemInit` enables CP10/CP11. Disassembly contains `vmul.f32` in the gated startup calculation and FP conversions/arithmetic including `vfma.f32` in the executed PI loop. This covers the fixture's instructions and IRQ use. |
| Flash prefetch and instruction/data cache | Register use observed, timing unsupported | HAL's normal writes to PRFTEN, ICEN and DCEN produce the known Renode warnings. The check audits those warnings. Cache effects, cycle accuracy and physical electrical timing remain outside scope. |
| APB1 divider changes | Implemented but untested in this fixture | The existing RCC patch derives timer clocks after a divider change. The HAL fixture uses APB1÷1 throughout. See the [peripheral qualification](peripheral-qualification.md) for the separate divider tests. |
| Other HAL features | Untested or outside this qualification | Arbitrary clock trees, RTOS startup, DMA, advanced timer functions, timebases beyond the selected HSI SysTick, and mixed/prioritized FP interrupt stress. |

The existing setup suite (5 tests), replay suite (6 tests), and full robot
regression passed. The latter included 22 robot hardware-path checks, motor
checks, 57 patched peripheral checks, firmware smoke and GDB checks. The
replay parser also accepted the HAL recording with the observer fields absent.

## Remaining genuine generation and IDE build

Install licensed [STM32CubeMX](https://www.st.com/en/development-tools/stm32cubemx.html)
or [STM32CubeIDE](https://www.st.com/en/development-tools/stm32cubeide.html) on
a machine with vendor download access. Install **STM32CubeF4 v1.28.3** in its
firmware package manager. In CubeMX or CubeIDE's device configurator:

1. Create a new **STM32F407VGT6** project. Select HSI directly as SYSCLK, disable
   PLL, and set AHB÷1, APB1÷1 and APB2÷2. Choose SysTick as HAL timebase, priority
   15. Use GNU STM32CubeIDE output and retain the generated `.ioc`.
2. Set PA4 and PA5 push-pull outputs initially high. Configure TIM2 internal
   upcounting, PSC 15, ARR 999, ARR preload enabled, CH1/CH2 PWM1 active high
   with initial pulse 0 on PA0/PA1 AF1. Enable the TIM2 global interrupt with
   preemption priority 1, subpriority 0 in priority group 4.
3. Set TIM3 and TIM4 to encoder mode TI1/TI2, direct rising inputs, PSC 0,
   ARR 65535, both input prescalers DIV1 and filters 0. Use PA6/PA7 and PB6/PB7
   AF2 respectively. Generate the project and retain its startup assembler,
   Flash linker script, CMSIS system code, HAL clock/peripheral code and ISR.
4. Add `robot.c` and `robot.h` as separate application files. In generated user
   sections, start both encoders with `HAL_TIM_Encoder_Start` and call
   `Robot_Start(&htim2, &htim3, &htim4)`. Start both TIM2 PWM channels, clear
   `TIM_FLAG_UPDATE`, and start TIM2 update IRQs with
   `HAL_TIM_Base_Start_IT`. Define `HAL_TIM_PeriodElapsedCallback` to call
   `Robot_Step`. For like-for-like qualification also retain the startup probes
   and 5 ms checked delay before peripheral initialization, using the
   handwritten fixture as a reference. Keep generated IRQ handlers forwarding
   to the HAL and avoid adding an example observer.
5. Import the project via **File → Import → Existing Projects into Workspace**
   if generated separately. Set Cortex-M4 Thumb hard-float FPv4-SP-D16 to
   match this qualification, then use **Build Project** and locate
   `Debug/<project>.elf`. Record the generator, IDE and compiler versions and
   keep the generated metadata. Where the installed IDE offers CDT headless
   builds, the corresponding command shape is
   `stm32cubeide -nosplash -application org.eclipse.cdt.managedbuilder.core.headlessbuild -data <workspace> -import <project-dir> -build <project>/Debug`.
   The invocation must be checked on the chosen IDE version.
6. Load that ELF through setup with the saved scenario and observer disabled.
   Compare discovery and repeat/load traces. The qualification script accepts
   `--elf` and assumes the documented controller sequence and startup probes.

The next milestone is to retain and build that generated project in the IDE,
then repeat the compatibility checks with its generated initialization.
