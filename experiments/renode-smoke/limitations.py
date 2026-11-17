"""Reproduce known model limitations; success confirms defects, not conformance."""
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
script = (HERE / 'out/smoke.resc').read_text().replace('\nquit\n', '\n')
script += '''# Diagnostic host writes only: test the model, not a firmware workaround.
sysbus WriteDoubleWord 0x40000400 0
sysbus.gpioPortA OnGPIO 6 true
emulation RunFor "0.001"
sysbus ReadDoubleWord 0x20000008
# HSI 16 MHz, APB1 /4 => 8 MHz timer clock on hardware.
sysbus WriteDoubleWord 0x40023808 0x1400
emulation RunFor "0.010"
sysbus.gpioPortA.probe Period
sysbus.gpioPortA.probe HighTime
quit
'''
(HERE / 'out/limitations.resc').write_text(script)
renode = Path(os.environ.get('RENODE_ROOT', '/workspace/tools/renode_1.17.0-portable')) / 'renode'
run = subprocess.run([str(renode), '--disable-gui', '--console', '--plain',
                      str(HERE / 'out/limitations.resc')], text=True,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
                     env=dict(os.environ, XDG_CONFIG_HOME='/workspace/.runtime-config'))
(HERE / 'out/limitations.log').write_text(run.stdout)
run.check_returncode()
assert not re.search(r'\[ERROR\]|No such command|There was an error|Failed to', run.stdout)
values = [int(x, 16) for x in re.findall(r'^0x([0-9A-Fa-f]+)\s*$', run.stdout, re.M)]
times = [float(x) for x in re.findall(r'^(0\.\d+)\s*$', run.stdout, re.M)]
if os.environ.get('RENODE_QUALIFIED') == '1':
    assert values[-1] == 0, values
    assert abs(times[-2] - .002) < 2e-9, times
    print('PASS: former limitation probes: disabled CNT=0, RCC APB1 /4 PWM period=2 ms')
else:
    assert values[-1] == 1, values
    assert abs(times[-2] - times[0]) < 1e-9, times
    print('CONFIRMED LIMITATION: CEN=0 still counts an encoder edge (CNT=1, expected 0)')
    print(f'CONFIRMED LIMITATION: RCC APB1 /4 leaves PWM period {times[-2]:.9f}s (expected about 0.002s)')
