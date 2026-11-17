#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p out
if [ "${RENODE_QUALIFIED:-0}" = 1 ]; then
  python3 ../../emulation/renode/prepare.py
fi
"${ARM_GCC:-/workspace/tools/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin/arm-none-eabi-gcc}" \
  -mcpu=cortex-m4 -mthumb -mfloat-abi=soft -g -O1 -ffreestanding \
  -nostdlib -Wl,--build-id=none -T link.ld firmware.c -o out/firmware.elf
python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ.get('RENODE_ROOT', '/workspace/tools/renode_1.17.0-portable'))
platform = (root / 'platforms/cpus/stm32f4.repl').read_text()
# SVD only labels unimplemented addresses; removing its download adds no peripheral.
platform = '\n'.join(line for line in platform.splitlines() if 'ApplySVD ' not in line)
# Explicit HSI 16 MHz profile. RCC does not propagate clock changes to timers.
platform = platform.replace('frequency: 10000000', 'frequency: 16000000')
platform = platform.replace('systickFrequency: 72000000', 'systickFrequency: 16000000')
if os.environ.get('RENODE_QUALIFIED') == '1':
    platform = platform.replace('Timers.STM32_Timer', 'Timers.QualifiedSTM32Timer')
    platform = platform.replace('Miscellaneous.STM32F4_RCC', 'Miscellaneous.QualifiedSTM32RCC')
    platform = platform.replace('    rtcPeripheral: rtc', '    rtcPeripheral: rtc\n    timer2: timer2\n    timer3: timer3\n    timer4: timer4')
    # Replace the selected input routes with AF-specific routes, retaining
    # the upstream output mux and all unrelated platform entries.
    import re
    for pin in (6, 7):
        pattern = r'(gpioPortA:\n(?:    [^\n]*\n)*?)    '+str(pin)+r' -> [^\n]*\n'
        platform, count = re.subn(pattern, lambda m: m[1]+'    '+str(pin)+' -> encoder'+str(pin)+'@0\n', platform, count=1)
        if count != 1: raise RuntimeError('upstream GPIO input route not found')
        platform += f'\nencoder{pin}: GPIOPort.STM32AFInput @ timer3\n    port: gpioPortA\n    pin: {pin}\n    alternateFunction: 2\n    IRQ -> timer3@{pin-6}\n'
platform += '\nprobe: Miscellaneous.EdgeProbe @ gpioPortA\ngpioPortA:\n    0 -> probe@0\n'
Path('out/stm32f4-hsi.repl').write_text(platform)
checkout = Path.cwd().parents[1]
script = Path('smoke.resc').read_text().replace('/workspace/EmbeddedSim', str(checkout))
if os.environ.get('RENODE_QUALIFIED') == '1':
    prefix = ''.join(f'include @{checkout}/emulation/renode/out/{name}.cs\n' for name in
                     ['QualifiedSTM32Timer', 'QualifiedSTM32RCC', 'STM32AFInput'])
    script = prefix + script
Path('out/smoke.resc').write_text(script)
PY
