# Use your own STM32 firmware

## HSI16 robot profile

Use a standalone STM32F407VGT6 Cortex-M4 Thumb ELF. The loader expects
little-endian ELF32 ARM EABI5, a reset vector and executable entry in
Flash at 0x08000000 (1 MiB), and an aligned initial stack in 128 KiB
SRAM or 64 KiB CCM. Firmware initializes its own data and BSS. The
qualified robot clock is HSI 16 MHz, AHB ÷1, APB1 ÷1, APB2 ÷2.

| Robot connection | Qualified setup |
| --- | --- |
| Left / right PWM | PA0 / PA1 AF1, TIM2 CH1 / CH2, active-high push-pull PWM1, edge-aligned up, PSC 15, ARR 999, 1 kHz |
| Left / right direction | PA4 / PA5 push-pull GPIO. High is forward |
| Left encoder A/B | PA6 / PA7 AF2, TIM3 CH1 / CH2 |
| Right encoder A/B | PB6 / PB7 AF2, TIM4 CH1 / CH2 |

Use direct TI1/TI2, SMS 3, PSC 0, ARR 65535, enabled noninverted inputs
without filtering. Complete A/B pairs can swap sides. Match the other
routes to your firmware's left/right mapping. Load a local ELF with
**Choose ELF**, leave **Firmware observer** at **None**, set wiring, and
inspect the final discovery snapshot for clock, AF, role and PWM period.
The robot still runs with physical pin signals and model feedback.
**EmbeddedSim example v1** reads a specific two-bank RAM telemetry ABI
for setpoints, estimates and odometry only. An invalid signature means
the observer selection needs changing. [Detailed setup contract](../../setup/README.md)

A loaded ELF may wait for a device, select incompatible clocks or leave
outputs unconfigured. Compare the reset and final snapshots and check
the first Renode warning, timer clock, PSC/ARR, GPIO mode, AF and signal
polarity. If needed, repeat discovery once with a longer virtual window
within the supported range to inspect later startup. Run checks serially.

## Independent compatibility evidence

A public STM32F407 ELF from kose25-m/Stm32f407-pwm-okuma at commit
`e8d74d4ff7f4e62f01b3f9edc14fc28b971e9c19` booted as-is. Its SHA-256
is `25c2ab9e6d21a4743d311e00e1adae5e45247c3a9a14d82579e27b95bb7f3353`.
The isolated bench verified TIM2 input capture, IRQ behavior and TIM3
PWM plus direction/brake GPIO response on the documented routes. In
the ordinary UI, use the passive **PLL168 discovery** profile for this
ELF. That profile has no robot wiring or closed-loop robot run. This
qualification covers the exact binary, clock tree and pin
configurations measured. Source-to-binary equivalence and arbitrary
CubeIDE projects remain unqualified. Obtain the ELF from upstream.
[Qualification and limits](../third-party-pwm-qualification.md) ·
[Current clock and discovery integration](../stm32f407-timebase.md)

## Collect diagnostics

Export the selected config, keep the exact ELF locally, save the UI job
ID, and find the job under `setup/out/jobs/` or
`EMBEDDEDSIM_ARTIFACTS`. For an independently reproducible discovery
job, from `source/` run:

```sh
sha256sum /path/to/your.elf
python3 setup/runner.py discover --config /path/to/wiring.json \
  --elf /path/to/your.elf --seconds 0.5 --output setup/out/own-discovery
```

Copy the relevant config, Renode log, discovery result or partial probe,
recording/event log if relevant, and the completed feedback template to
a separate review directory. Inspect every file before archiving that
directory. Paths, symbols, register values, hardware details and recorded
behavior can be sensitive. A debug ELF may expose source paths and
symbols. Leave proprietary ELF bytes, sources, maps and credentials out
unless you have permission to share them. List omissions and supply a
hash or small shareable reproducer when appropriate. The local server
does not submit these files to anyone.
