# STM32F407 external-ELF time-base qualification

The unchanged third-party PWM ELF now boots and reports its actual pin roles
through the standard external-ELF discovery command. The
`pwm-signal-pll168-v1` profile is passive and uses the same STM32F407 platform
as the signal tests. The differential-drive preset retains its existing
connections.

The original is the ELF at commit `e8d74d4ff7f4e62f01b3f9edc14fc28b971e9c19`
with SHA-256
`25c2ab9e6d21a4743d311e00e1adae5e45247c3a9a14d82579e27b95bb7f3353`.
The [original qualification](third-party-pwm-qualification.md) documents
its provenance and the original bit-band and SysTick gaps. The comparison
below uses the same ELF and preserves that report's raw results.

## Root cause and correction

The STM32F407 routes HCLK to SysTick when CSR.CLKSOURCE is 1 and HCLK/8
when it is 0. For a periodic tick, the firmware computes LOAD as one
less than the number of selected clocks per tick. See the SysTick section
in ST's [PM0214 programming manual](https://www.st.com/resource/en/programming_manual/dm00046982.pdf)
and the RCC clock tree in [RM0090](https://www.st.com/resource/en/reference_manual/dm00031020.pdf).

The original ELF's `HAL_InitTick` loads `SystemCoreClock` and divides it
by the HAL tick rate before calling CMSIS `SysTick_Config`. Disassembly
shows the reload store at `0x0800237c`, the current-value clear at
`0x0800238c` and the CSR store of 7 at `0x08002392`. In
`HAL_RCC_ClockConfig`, the store at `0x08002e24` updates
`SystemCoreClock`, and the call at `0x08002e2c` reconfigures the HAL tick.
Firmware requests the processor clock, enables the exception and
uses the appropriate reload values. It does not account for the
simulator's former fixed frequency.

The stock Renode NVIC held SysTick at the configured 16 MHz and exposed
CLKSOURCE as read-only high. The resulting tick spacing followed
the wrong physical clock, even though IRQ delivery and HAL software
increments agreed with one another. The
[additional RCC source patch](../emulation/renode/patches/0003-systick-clock.patch)
feeds HCLK from the qualified RCC clock tree into the existing NVIC.
The STM32F407 clock adapter applies and reads back the selected divider.
The NVIC still owns the counter, pending exceptions and interrupt delivery.
No CPU throughput settings, original firmware instructions, firmware delay
constants, or HAL variables were changed.

## Measurements against virtual time

The [measurement summary](evidence/stm32f407-timebase-results.json) contains both runs.

Renode's clock-source timestamps are used for both pin-event and paused
register observations. On the original ELF, the early snapshots show
HCLK 16 MHz, LOAD 15999 and `uwTick=0` from 16 to 22 µs. PLL is selected
by 23 µs. `SystemCoreClock` is 168 MHz by 25 µs and LOAD is 167999 by
26 µs. The pre-PLL interval is shorter than one tick. The separate
compiled HAL fixture keeps the initial HSI mode long enough to measure
its steady cadence.

| Clock and SysTick source | IRQ spacing before, median | IRQ spacing after, median | `HAL_Delay(10)` before → after |
| --- | ---: | ---: | ---: |
| HSI, HCLK 16 MHz | 0.99994 ms | 0.99994 ms | 10.997 → 10.997 ms |
| HSI PLL, HCLK 168 MHz | 10.49994 ms | 0.99999 ms | 115.498 → 10.999 ms |
| PLL with AHB÷2, HCLK/8 = 10.5 MHz | 0.65619 ms | 0.99991 ms | 7.217 → 10.993 ms |
| Return to HSI, HCLK 16 MHz | 0.99994 ms | 0.99994 ms | 10.999 → 10.999 ms |

The fixture toggles an observation pin inside the SysTick handler and
another around the same `HAL_Delay(10)` call in every clock state. In
each case the handler count and `HAL_GetTick()` both increase by 11,
consistent with the HAL delay guard. With TICKINT clear it also measures
a separate counter wrap through COUNTFLAG at 1.000 ms and verifies the
handler count stays unchanged. This distinguishes the counter's timing
from IRQ delivery and the HAL tick variable. The same compiled check
fails on the legacy PLL timing.

The original ELF's symbol-resolved `uwTick` changes from 1 to 6 on the
legacy clock and from 19 to 68 with the fix, over the same virtual interval
20.000–68.984 ms. These are paused, read-only observations of ordinary
firmware symbols. They require no example RAM observer.

## Bit-band mapping and the original signal tests

The qualified motor, robot and PWM signal platform definitions enable
one Renode peripheral bit-band alias over `0x42000000–0x43ffffff` for
peripheral space starting at `0x40000000`. No SRAM bit-band mapping is
included or qualified. The compiled HAL fixture reads, sets and clears
an AHB1 GPIO gate while preserving a neighboring enable bit, and reads,
sets and clears the APB1 TIM2 gate. It verifies the original PLLON
alias at `0x42470060`, then switches back to HSI and verifies clearing
PLLON and deasserting PLLRDY while HSI remains ready.

The unchanged ELF's negative control without the alias reaches
`Error_Handler` after polling PLLRDY. With the alias and clock fix,
the same tests observe both capture channels, ISR polarity changes, 96
timestamped input-pin transitions, and 24/16/24 IRQ assertions in the
split/neutral/swapped phases. Split and swapped duties are 61.52% and
58.04% on the two pairs. Neutral outputs stay low, with the shared
brake asserted. These phase results match the legacy-clock signal
results. Before the first pulses, all four outputs still command
near-full reverse with CCR=8561. The measured PWM period is
407.715 µs versus 407.714 µs calculated from the observed APB1
timer clock (84 MHz), PSC=3 and ARR=8561.

## Reproduce and discover

Run the focused verification from the repository root with the preserved
ELF and a fresh output directory. The original report contains the
pinned Git extraction steps if the local ELF is unavailable.

```sh
bash tests/timebase/verify.sh \
  /workspace/shared/stm32f407-pwm-okuma/Example.elf setup/out/timebase-recheck
```

The command records the legacy timing failure and corrected timings,
runs both original-ELF signal comparisons, and exercises the standard
loader and discovery CLI. For passive discovery alone:

```sh
python3 setup/runner.py discover --config setup/pwm-signal.json \
  --elf /workspace/shared/stm32f407-pwm-okuma/Example.elf \
  --seconds 0.02 --output setup/out/external-pwm-discovery
```

The discovery JSON records HCLK, both PCLKs, the APB1 timer clock,
capture roles and counter frequency, and configured versus observed
PWM timing. The discovery profile rejects robot wiring and simulation
runs. Using the robot profile on this ELF gives a clock/profile mismatch
diagnostic. The robot UI and robot connections are unchanged. Drive
the test inputs through the signal qualification command rather than
through passive discovery.

## Regression results

The focused timing/discovery command, the existing STM32CubeF4 HAL fixture,
five setup tests, six replay tests, and the combined robot, motor,
peripheral, firmware smoke and GDB checks passed. The combined suite
included 22 robot hardware-path checks and 57 patched peripheral checks.
All seven existing robot and physics CSV hashes matched the retained
evidence.

## Limits

ITM/SWO delivery, active TIM9 behavior, broader SysTick calibration and
deep-sleep behavior are unqualified. The patch leaves the stock NVIC's
counter semantics in place. In the steady IRQ measurements the remaining
error is on the order of one selected-clock tick or observation latency,
so these checks do not establish single-clock rollover accuracy.
All timing is virtual. Cycle accuracy and physical hardware validation
are outside this qualification.
