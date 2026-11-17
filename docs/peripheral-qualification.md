# F407 motor-loop peripheral qualification

This records the peripheral milestone. The subsequent [motor-loop report](motor-loop.md)
implements and verifies the physical feedback loop using this same profile.

17 November 2026. This qualifies a **limited Renode peripheral profile**, not
the complete STM32F407. No motor model or UI is implemented.

## Reproduce

From any checkout path on this x86-64 Linux environment:

```sh
bash tests/peripherals/check.sh
```

This checks/downloads the pinned tools, applies source patches, compiles real
Cortex-M4 firmware, runs the 57 headless firmware checks, and reruns the
original ELF, PWM/encoder, virtual-time, GDB and former-limitation experiments.
Failures return nonzero. Subprocesses and the overall stages have wall-clock
timeouts; functional assertions use virtual time. Logs, generated sources,
platforms, ELF and JSON are ignored under `out/` directories.

Prerequisites: Python 3, Bash, GNU patch, coreutils (`timeout`, `sha256sum`),
curl, tar, glibc Linux x86-64. No SDK or system package installation is needed:
Renode's portable package includes its .NET runtime and C# source compiler.
The first setup downloads the Renode and xPack GCC archives from GitHub
releases/release-assets; subsequent runs can use the checksum-verified cache
in `/workspace/research/downloads`. Tools live under `/workspace/tools`;
configuration lives under `/workspace/.runtime-config`, avoiding read-only HOME.
The selected checkout is already isolated; no worktree is needed.

For the deliberately failing stock comparison:

```sh
python3 tests/peripherals/run.py --stock
```

The stock command returns nonzero and can abort its emulator on encoder wrap;
this is an expected baseline failure, not a setup success. To reproduce only
the historical smoke, use the original README commands without
`RENODE_QUALIFIED=1`. `check.sh` explicitly selects the patched profile for
those experiments.

## Provenance and reproduced baseline

- Renode binary: **1.17.0+20260907gitf1dd1b4af**, Release, .NET 8.0.12;
  archive SHA-256 is pinned in `experiments/renode-smoke/bootstrap.sh`.
- Source tag: `v1.17.0`, Renode
  `ab721d88e135a1bcb8ed2ecc5a38f51cbe61fdd2`; infrastructure
  **`066a7f13c052215632d469c995c89aea37c573b1`**. Tag and binary build suffix
  differ; these are identified separately rather than assumed identical.
- Compiler: xPack GNU Arm GCC **15.2.1**, package **15.2.1-1.1**, compiler
  banner dated 20251203; Cortex-M4 Thumb, soft float, `-O1 -g`, freestanding,
  no runtime libraries. GDB **16.3.90.20250906-git** from the same package.
- Host: Debian 13.6 x86-64, Python **3.12.14**, GNU patch **2.8**.
- The existing files were untracked on an unborn `work` branch, with no
  repository AGENTS.md. Existing work was retained; no commits/pushes made.

Before changes, these commands were run again, rather than relying on the
previous report: `bootstrap.sh`, `verify.py`, `gdb_check.py`, `limitations.py`.
They reproduced ELF marker `0xC0DEF407`, 10 original smoke ISR increments,
999 us PWM period / 250 us high time, encoder 4→0, 12 ms virtual time, GDB
break/step/read/detach, counting while CEN=0 and fixed clocks after APB changes.

The new suite initially failed against stock before fixes. Final comparison:

| Run | Actual outcome |
|---|---|
| Stock firmware regression | 15 passed, 40 failed assertions, 2 uncompleted wrap observations; emulator aborts on forward wrap with `ArgumentException: Value cannot be larger than limit`. JSON also records the emulator-completion failure (15/58 entries). Underflow cannot be qualified on that aborted stock run. |
| Patched firmware regression | **57/57 passed**, normal emulator exit; no skipped/expected-failure checks. |
| Patched original experiments | Boot/ELF, PWM, encoder, 12 ms time advancement, GDB ISR breakpoint/RAM read/single step/detach pass. Former limitation probes now read disabled CNT=0 and APB1÷4 period=2 ms. |
| Clean checkout simulation | Same command passed from `/tmp/EmbeddedSim-repro-final`, copied without `.git`, generated outputs or bytecode caches, using retained dependency archives. No absolute original-checkout source path is required. A brand-new machine/tool download was not retested. |

Machine-readable results with source revisions, firmware/source hashes,
compiler version and trace fingerprint are retained in `docs/evidence/`.
The clean-copy trace fingerprint matched the original run. ELF file hashes
may differ across paths because debug information contains compilation paths.

The corrected smoke observes 9 ISR increments and 11 rises/10 falls at its
10 ms snapshot: PWM includes the initial high level at time zero and a rise
at the exact 10 ms endpoint; the pending 10th interrupt needs another CPU
instruction to enter its handler. The new IRQ tests compare settled count
deltas over complete virtual-time windows instead of counting startup events.

## Hardware contract checked

ST's direct PDF URL for RM0090 returned HTTP 403. I consulted the accessible
**RM0090 Rev 18 extracts** at mirror commit
`0be080be030e3365c122995ec630f413bb1af239` [1–6], and cross-checked normal
initialization against ST's own HAL source at
`6ef30cf0ef6cc29ad518f37b9e6de89b6b815f90` [7]. The mirror is a transcription,
not a newly downloaded manufacturer PDF; relevant section/page identifiers
are preserved for review against the original.

For edge-aligned upcounting:

```text
fCNT = fTIM / (PSC + 1)
period = (ARR + 1) / fCNT
PWM1 high time = min(CCR1, ARR + 1) / fCNT
```

RM0090 §18.3.1 (p591) makes PSC buffered until UEV and ARR conditional on
ARPE. §18.3.2 shows the inclusive 0…ARR sequence. §18.3.9 (pp610–611)
defines CCR preload/UG, high while CNT<CCR, CCR=0 low, CCR>ARR high.
§18.4.1 states encoder mode requires software CEN. §18.4 SMCR describes
SMS=3 counting both TI1/TI2 edges. §7.2 states APB timers use PCLK when the
APB divisor is 1 and **2×PCLK otherwise**. §7.3.2 requires reserved PLLCFGR
bits to retain reset values.

The first draft of the new test firmware overwrote PLLCFGR reserved bit 29.
The warning audit caught it; firmware now changes only PLLM/N/P/Q/SRC fields
with read-modify-write, consistent with the hardware contract. This was a
firmware error, not a Renode defect.

## Exact qualified configurations

The reusable platform is `emulation/renode/stm32f407vg.repl`: Cortex-M4,
1 MiB flash at 0x08000000, 128 KiB main SRAM and 64 KiB CCM SRAM. It contains
the selected peripherals and startup dependencies, not a complete board.

| Function | Tested configuration |
|---|---|
| PWM | **TIM2_CH1 → PA0, AF1**, push-pull default, active-high PWM1, edge-aligned upcount, CC1E=1. Wrong MODER=input and wrong AF0 disconnect output; restoring AF1 restores it. |
| Encoder | **PA6/PA7, AF2 → TIM3_CH1/CH2**, direct TI1/TI2, SMS=3, CC1E/CC2E=1, no inversion, no digital filter, ARR=65535. A↑ B↑ A↓ B↓ counts +4; reverse counts −4. CEN stop/re-enable, APB enable gating, reset/reinitialize, both wrap directions and wrong MODER/AF are tested. Mode/AF changes in these tests happen with A=B=0. |
| Control tick | **TIM4 update → NVIC IRQ30**, interrupt enabled; firmware verifies UIF, clears it with rc_w0, checks readback, and continues counting. Stop/resume, APB clock gate/resume and reset stop delivery. UG sets UIF even with UIE=0. |

Use **HSI16, AHB÷1, APB1÷1, APB2÷2** for the first motor loop: TIM2 PSC15/ARR999,
initial CCR250 with both preloads enabled, TIM3 as above, and TIM4
PSC15/ARR999. That gives 1 kHz PWM and a 1 ms control tick. The PLL settings
below are additional tested clock configurations, not a requirement to start.

PWM PSC/ARR/CCR tuples `(15,999,250)`, `(0,1599,800)`, `(7,1999,1500)`,
`(31,999,100)` are tested at HSI16 with both ARPE/OC1PE disabled and both
enabled. At PSC15/ARR999 with preloads disabled, CCR0, CCR1000 and CCR1200
are constant outputs.
With both preloads enabled, natural UEV transfers PSC15→31, ARR999→1999,
and CCR250→750 without a malformed intermediate pulse. Software UG while
stopped transfers all three shadows before restart, including the first
counter cycle. Normal tests use UDIS=0 and URS=0.

| Clock source | HPRE divisor | APB1 divisor | PCLK1 | TIM2/3/4 input |
|---|---:|---:|---:|---:|
| HSI16 | 1 | 1 | 16 MHz | 16 MHz |
| HSI16 | 1 | 2 | 8 MHz | 16 MHz |
| HSI16 | 1 | 4 | 4 MHz | 8 MHz |
| HSI16 | 2 | 4 | 2 MHz | 4 MHz |
| HSE8 | 1 | 1 | 8 MHz | 8 MHz |
| HSE8/PLL168 | 1 | 4 | 42 MHz | 84 MHz |
| HSE8/PLL168 | 1 | 8 | 21 MHz | 42 MHz |

PLL uses M=8, N=336, P=2, Q=7. Firmware first switches to ready HSI, disables
PLL before programming, enables/waits for HSE/PLL, sets voltage scale and
five flash wait states, then switches and polls SWS. Explicit clock setups
use APB2÷2 (the initial reset-state tests begin at APB2÷1); no APB2 peripheral
rate is qualified. At each table entry PWM uses
PSC7/ARR999/CCR250 and TIM4 uses a 1 MHz counter/ARR999 for a 1 ms tick.
A running PWM timer also follows HSI16/APB1÷1 → HSI16/APB1÷4 without timer
reinitialization. Assertions cover settled rates, not exact phase across a
clock switch. Rates in the table are verified through TIM2 and TIM4; TIM3's
external-edge counting and clock gating are tested at HSI16, not as an
internally clocked counter. Host code never rewrites emulated timer Frequency
properties.

## Repairs and measurement findings

The upstream files are vendored unchanged with their MIT license and SHA-256
checks. `prepare.py` applies the two patches with **zero fuzz**, then
mechanically renames the types. Renode's documented source-loader path
compiles them on `include`; stock `Infrastructure.dll`, CPU and native
execution engine remain untouched. This is a reproducible source extension,
not a manually edited binary or a claim that a full Renode source build ran.

- **Timer patch:** use ARR+1 for the exclusive `LimitTimer` period; distinguish
  pending PSC/CCR from active values; transfer shadows at natural UEV/UG;
  honor encoder CEN and clock gating; wrap within ARR, update DIR and UIF;
  keep the compare timers' frequency/divider aligned with the parent.
- **RCC patch:** derive attached APB1 timer clocks from source, PLL, HPRE and
  PPRE1; apply the ×2 rule; propagate enable and reset. This logic belongs
  to the emulated RCC and is driven by actual firmware register writes.
- **Input routing:** a small generic `STM32AFInput` component connects a
  physical pin to an AF consumer only in the selected mode/AF. Pin/AF/channel
  selection is platform data; no hard-coded firmware address or speed input
  is used. Existing GPIO output AF routing is retained.
- **Probe fix:** record `machine.ClockSource.CurrentValue`, not the machine's
  CPU-reported elapsed time. The latter introduced roughly instruction-sized
  timestamp jitter at PLL rates. Correct clock-domain sampling passes a
  **2.1 ns** period/high-time tolerance, well below a counter tick in every
  tested configuration. This was a measurement error distinct from the
  genuine ARR off-by-one: stock remains 999 us after corrected measurement,
  while the patched steady period is 1000 us.

Tests communicate commands through a normal RAM mailbox; the compiled ELF
performs every timer/RCC/GPIO register write. External code supplies A/B edges
and observes actual PWM. The legacy limitation diagnostic still performs
its explicit host MMIO writes; it is supplementary, not the firmware proof.
The two expected FLASH cache-enable warnings are retained in `warnings.log`:
PRFTEN/ICEN/DCEN are stored tags, not simulated CPU caches. All other model
warnings/unimplemented accesses fail the patched suite. Cache bits were not
removed from firmware to conceal this limitation.

## Limits and next task

The selected paths pass; no required path in this **scoped configuration** is
blocked. This does not qualify arbitrary STM32 firmware, complete HAL/RTOS
startup, other channels/timers, center/down counting, PWM2/inversion,
independent preload-flag combinations, input filters/prescalers, encoder
modes 1/2, arbitrary polarity, encoder overflow IRQ delivery, DMA, advanced
timers, or GPIO remux while inputs are high. ARR=0 and extreme full-width
timer periods are not qualified. Reset/clock gating of GPIOA registers is
not modeled by the new adapter; tests enable GPIOA normally.

Oscillator-ready flags remain instantaneous. CPU instruction scheduling,
SysTick and unrelated peripheral clocks are not driven by this RCC extension;
the control tick must use qualified TIM4. Clock-switch phase continuity,
cache behavior and Cortex-M4 cycle accuracy are not claimed. The generic
historical smoke still uses a broader memory map; only the new profile has
the selected chip's memory sizes. Hardware comparison remains desirable.

**Next task:** add an emulator-independent DC motor/driver model and a
virtual-time adapter. Measure TIM2 PWM edges, integrate voltage/current/speed/
angle, generate time-ordered quadrature edges into PA6/PA7, and let real
firmware read TIM3 and update TIM2 in TIM4's ISR. First prove open-loop duty
and direction responses, encoder edge conservation and timestep convergence;
then add the firmware speed controller and deterministic speed/load steps.
Do not set CNT from the host, couple physics with wall-clock sleeps, or add a
GUI yet.

## References inspected

1. [RM0090 §18.3.1, time base and PSC/ARR buffering](https://github.com/mdarin/halo-stm32f4xx-mcp/blob/0be080be030e3365c122995ec630f413bb1af239/kb/stm32f4xx/reference/18_18_3_1_Timebase_unit.md)
2. [§18.3.2, inclusive upcounter sequence](https://github.com/mdarin/halo-stm32f4xx-mcp/blob/0be080be030e3365c122995ec630f413bb1af239/kb/stm32f4xx/reference/18_18_3_2_Counter_modes.md)
3. [§18.3.9, PWM comparison and preload/UG](https://github.com/mdarin/halo-stm32f4xx-mcp/blob/0be080be030e3365c122995ec630f413bb1af239/kb/stm32f4xx/reference/18_18_3_9_PWM_mode.md)
4. [§18.4, CR1/CEN](https://github.com/mdarin/halo-stm32f4xx-mcp/blob/0be080be030e3365c122995ec630f413bb1af239/kb/stm32f4xx/reference/18_18_4_TIM2_to_TIM5_registers__c02.md), [SMCR encoder modes](https://github.com/mdarin/halo-stm32f4xx-mcp/blob/0be080be030e3365c122995ec630f413bb1af239/kb/stm32f4xx/reference/18_18_4_TIM2_to_TIM5_registers__c04.md)
5. [§7.2, APB multiplier](https://github.com/mdarin/halo-stm32f4xx-mcp/blob/0be080be030e3365c122995ec630f413bb1af239/kb/stm32f4xx/reference/07_7_2_Clocks.md)
6. [§7.3.2, PLLCFGR formulas/reserved bits](https://github.com/mdarin/halo-stm32f4xx-mcp/blob/0be080be030e3365c122995ec630f413bb1af239/kb/stm32f4xx/reference/07_7_3_2_RCC_PLL_configuration_register_RCCPLLCFGR.md)
7. [ST HAL time-base initialization: ARR/PSC, URS and UG](https://github.com/STMicroelectronics/stm32f4xx-hal-driver/blob/6ef30cf0ef6cc29ad518f37b9e6de89b6b815f90/Src/stm32f4xx_hal_tim.c#L6796)
8. [Pinned upstream timer source](https://github.com/renode/renode-infrastructure/blob/066a7f13c052215632d469c995c89aea37c573b1/src/Emulator/Peripherals/Peripherals/Timers/STM32_Timer.cs), [RCC source](https://github.com/renode/renode-infrastructure/blob/066a7f13c052215632d469c995c89aea37c573b1/src/Emulator/Peripherals/Peripherals/Miscellaneous/STM32F4_RCC.cs)
