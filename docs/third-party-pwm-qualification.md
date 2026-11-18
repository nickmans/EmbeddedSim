# Original third-party STM32F407 PWM ELF qualification

This report records the original bench and fixed-clock measurements.
The [time-base follow-up](stm32f407-timebase.md) covers the shared bit-band
mapping, corrected SysTick behavior and normal-workflow discovery.

The committed **original** ELF boots and responds to two external PWM inputs
on the isolated signal bench on Renode 1.17.0+20260907gitf1dd1b4af.
See the [machine-readable measurements](evidence/third-party-pwm-results.json). The regular robot profile lacks the peripheral
bit-band alias required by this firmware. The bench uses Renode's existing
alias model plus the project's physical GPIO routes. No simulator core,
robot preset, firmware bytes, or example RAM observer were changed. The
bench drives input pin levels and records output pin events and read-only
snapshots. It contains no four-motor physics model.

## Binary and provenance

| Item | Observed |
| --- | --- |
| Source and object | [Pinned public repository tree](https://github.com/kose25-m/Stm32f407-pwm-okuma/tree/e8d74d4ff7f4e62f01b3f9edc14fc28b971e9c19), commit `e8d74d4ff7f4e62f01b3f9edc14fc28b971e9c19`. `Debug/Example.elf` is Git blob `d2a71691a737208412e71c2f605f83d4241c6101`. The commit adds the README. The ELF, source and build artifacts were already present in `da7cac4`. |
| SHA-256 | `25c2ab9e6d21a4743d311e00e1adae5e45247c3a9a14d82579e27b95bb7f3353`. The qualified copy is extracted directly from Git and the harness rejects any other bytes. |
| Validation | Passed the setup loader's ELF validation. Static little-endian ELF32 ARM EABI5, hard-float, ARMv7E-M Thumb-2 with VFPv4-D16, single-precision FP and VFP register arguments. |
| Load segments | `0x08000000` RX, length `0x73d8`. `0x20000000` RW, `0x1d4` initialized bytes stored at `0x080073d8`. SRAM zero-fill segment at `0x200001d4`, memory length `0x8c4`, no file bytes. The harness loads the validated file-backed bytes and the stock reset code initializes RAM. |
| Vectors | Flash base `0x08000000`. MSP `0x20020000`, reset and ELF entry `0x080020cd`, HardFault `0x08001ee9`, SysTick `0x08001f33`, TIM2 IRQ28 `0x08001f41`. The handler addresses carry the Thumb bit. |
| Build evidence | ELF `.comment` contains GNU Tools for STM32 `12.3.rel1.20240612-1315`, GCC 12.3.1 (20230626). `Debug/Core/Src/subdir.mk` and `Debug/makefile` show matching Cortex-M4 Thumb hard-float options, Debug `-O0 -g3`, nano/nosys specs and `-u _printf_float`. The makefile references `STM32F407VGTX_FLASH.ld`. |
| Generated-project evidence | The README describes a CubeMX skeleton with user sections. `Example.ioc` records CubeMX 6.12.0, database DB.6.0.120 and STM32Cube FW_F4 v1.28.1. Committed `.cproject`, `.mxproject`, startup and build outputs corroborate the workflow. DWARF and symbols identify the RCC, capture callback and error handler discussed here. These checks support provenance. Exact source-to-binary identity and the IDE build itself were not independently reproduced. |

Reviewed the pinned README, `Example.ioc`, IDE and Debug make metadata,
`Core/Startup/startup_stm32f407vgtx.s`, Flash and RAM linker scripts, and
`Core/Src/main.c`, `stm32f4xx_it.c`, `stm32f4xx_hal_msp.c` and
`system_stm32f4xx.c`. GPIO and timer routing below reflects the committed
source and the matching register state seen during execution. No modified
or rebuilt ELF variant was used. Keep the original binary in an ignored
download location and obtain it from the upstream repository.

## Startup and clock initialization

The existing observer-disabled robot discovery command advanced to 0.5 s
virtual time and returned snapshots, but initialization had failed. Its log
recorded firmware writes of both 0 and 1 to unmapped address `0x42470060`.
The signal bench reproduces the failure in a 20 ms negative control. At the
snapshot its PC resolves to `Error_Handler`, `RCC_CR=0x00000483`,
`RCC_CFGR=0`, `SystemCoreClock=16 MHz`, and TIM2 remains stopped. The write of
1 resolves through DWARF to `HAL_RCC_OscConfig` at the PLL enable step.
ST's HAL uses the Cortex-M4 peripheral bit-band alias of `RCC_CR` bit 24
(PLLON): `0x42000000 + (0x40023800 - 0x40000000) * 32 + 24 * 4`. With the
write unhandled, PLLRDY remains clear and HAL times out.

Enabling the standard Renode `Miscellaneous.BitBanding` peripheral alias in
the otherwise identical bench allows original firmware startup to complete.
At 20 ms `RCC_CR=0x03000483`, `RCC_PLLCFGR=0x24002a08`,
`RCC_CFGR=0x0000940a`, and firmware reports 168 MHz. This is HSI16 divided by
8, multiplied by 168 and divided by 2, with AHB÷1, APB1÷4 and APB2÷2.
The verified APB1 timer clock is 84 MHz. Firmware itself performs all
register writes. See the [STM32F4 reference manual](https://www.st.com/resource/en/reference_manual/dm00031020.pdf)
and the STM32F4 platform shipped with Renode for the alias mapping.

## Pin discovery and input capture

The robot discovery catalog describes a different set of roles. The
bench snapshots the firmware's own settings while the machine is paused,
with untouched initial pin state retained as a comparison.

| Pins | Discovered configuration and scope |
| --- | --- |
| PA0, PA2 | AF1 direct TIM2 CH1 and CH3 input capture, rising initially, no filter or input prescaling. PA2 has a pull-up in the committed code and observed GPIO settings. The bench drives both lines low initially. |
| PA6, PA7, PB0, PB1 | AF2 TIM3 CH1–CH4 active-high PWM1. PSC=3, ARR=8561, four channels enabled. Output period predicted from hardware counter timing is 407.714 µs. |
| PC0–PC3 | Four push-pull direction outputs. High is forward in the committed logic. |
| PB3, PB5 | Shared push-pull brake pair. Drive is PB3 high/PB5 low and brake is PB3 low/PB5 high. Per-motor brake isolation is absent. |
| PE5, PE6 | AF3 TIM9 CH1/CH2 configured, with CEN and channel enables clear. TIM4 is also initialized and stopped. |

TIM2 uses PSC=83 and ARR=2040 (1 µs per count, 2041 counts per wrap).
CH1 and CH3 interrupts are enabled and NVIC accepts TIM2 IRQ28. The bench
sends eight pulses per phase at a 2041 µs period using virtual-time GPIO
changes. The input taps confirmed all 96 transitions at the scheduled
virtual times. The IRQ wire is observed as a separate signal. After the first
coincident rises, both capture polarities change to falling before either
fall arrives. At each phase's end both have returned to rising. The bench
also reads ordinary firmware symbols by their ELF addresses to corroborate
the ISR calculations. These reads are paused observations and supply
neither firmware data nor control inputs.

The code scales measured high time by 2040, not by the measured period of
the incoming signal. The chosen test period is close to that constant.
Its wrap branch omits the inclusive counter's extra tick. The measured
firmware high-time values are therefore 699, 1019 and 1399 µs for the
700, 1020 and 1400 µs input widths used here. This observed one-count
difference follows the original application arithmetic.

## Output response

Below 49% and above 51%, the source sets reverse and forward respectively,
sets the shared brake pair to drive, and computes the compare value from
its adjusted duty. The neutral band sets zero compare and brakes while
leaving the previous direction state. PA2 controls outputs CH1/CH2 and
PA0 controls CH3/CH4. The harness checks the original formula against
the observed capture count, compares CCR to measured pin high-time, and
checks external brake/direction pin levels. Combined CH1/CH3 IRQ assertions
can coalesce when edges occur at the same virtual time.

| Phase (PA0/PA2 high time) | Measured PWM duty CH1/2 | Measured PWM duty CH3/4 | PC0/1, PC2/3 | PB3/PB5 | Shared IRQ assertions |
| --- | ---: | ---: | --- | --- | ---: |
| Split (700/1400 µs) | 61.52% | 58.04% | high, low | 1/0 | 24 |
| Neutral (1020/1020 µs) | 0%, constant low | 0%, constant low | high, low retained | 0/1 | 16 |
| Swapped (1400/700 µs) | 58.04% | 61.52% | low, high | 1/0 | 24 |

Before the first input edges, both firmware duty variables are zero. The
boot snapshot shows all four compare registers at 8561, direction low,
and PB3/PB5 at 1/0. The source treats missing startup pulses as its
low-duty reverse command.

The observed active period is 407.715 µs in the settled windows. Brake
and direction labels describe logic levels only. Mixed neutral/active
inputs can cause conflicting assignments to the shared brake pair within
one main-loop iteration in the source. That case and physical brake
behavior were outside the qualification. The harness stops at 68.984 ms
virtual time and uses a 45 s wall timeout for each emulator process.

## Unsupported paths

- **SysTick under PLL.** The firmware sets reload to 167999 after its clock
  switch, while the bench's existing NVIC SysTick clock remains 16 MHz.
  The firmware tick increases by five between the 20 ms and 68.984 ms
  snapshots. One-millisecond HAL tick accuracy under PLL is consequently
  outside this bench. TIM2 capture and TIM3 PWM are clocked by the patched RCC.
- **Debug transport.** The strong linked `_write` calls CMSIS
  `ITM_SendChar`. The log shows reads of ITM TCR at `0xe0000e80` from that code.
  The unimplemented address returns a disabled state and the application
  continues. The committed debug launch enables SWV at 168 MHz and includes
  ITM stimulus port 0. SWO delivery, ITM backpressure and debugger-connected
  operation were not qualified. PB3 is also the TRACESWO-capable pad, and the
  firmware configures it as a brake GPIO. The bench did not test this pin-mux
  interaction. The linked output path uses ITM and has no UART dependency.
- **TIM9 and other peripherals.** TIM9 is mapped for its initialization
  writes. Its APB2 clock tracking and shared interrupt line are outside
  the bench. The TIM4 and TIM9 counters are stopped in this tested application.
  GPIOH is clock-enabled without observed data accesses.
- The logs retain the expected Flash cache/prefetch tag warnings and a
  warning on the firmware's RCC PLLCFGR reserved bit write. Cache effects,
  analog pin behavior, physical motor dynamics and MCU cycle accuracy
  were not measured.

## Reproduce without ST tools

From the EmbeddedSim root, use a fresh output path for each run.

```sh
bash experiments/renode-smoke/bootstrap.sh
mkdir -p setup/out
git clone --no-checkout https://github.com/kose25-m/Stm32f407-pwm-okuma.git setup/out/pwm-upstream
git -C setup/out/pwm-upstream show e8d74d4ff7f4e62f01b3f9edc14fc28b971e9c19:Debug/Example.elf \
  > setup/out/pwm-original.elf
sha256sum setup/out/pwm-original.elf
python3 setup/runner.py discover --config setup/default.json \
  --elf setup/out/pwm-original.elf --output setup/out/pwm-original-robot-catalog
python3 tests/third-party-pwm/check.py --elf setup/out/pwm-original.elf \
  --output setup/out/pwm-original-evidence
```

The signal check runs its negative control before the bounded signal
test and retains headers, pin stimuli, observed transitions, raw
snapshots, symbolized failure PC, logs and a JSON summary. The successful
shell exit of the regular discovery command means it captured snapshots.
The negative control and its logs establish the startup failure.


The existing setup suite (5 tests), replay suite (6 tests), and combined
robot regression passed. The combined run included the motor suite, 22
robot hardware-path checks, 57 patched peripheral checks, firmware
smoke and GDB.
