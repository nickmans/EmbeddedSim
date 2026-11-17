"""Run the diagnostic and assert actual outputs, since Monitor errors may exit 0."""
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
renode = Path(os.environ.get('RENODE_ROOT', '/workspace/tools/renode_1.17.0-portable')) / 'renode'
env = dict(os.environ, XDG_CONFIG_HOME='/workspace/.runtime-config')
subprocess.run(['bash', str(HERE / 'build.sh')], check=True, env=env)
command = [str(renode), '--disable-gui', '--console', '--plain', str(HERE / 'out/smoke.resc')]
run = subprocess.run(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT, timeout=60)
(HERE / 'out/smoke.log').write_text(run.stdout)
print(run.stdout)
run.check_returncode()
assert not re.search(r'\[ERROR\]|No such command|There was an error|Failed to', run.stdout)
hexes = re.findall(r'^0x([0-9A-Fa-f]+)\s*$', run.stdout, re.M)
values = [int(x, 16) for x in hexes]
expected = [0xC0DEF407, 9, 11, 10, 4, 0] if os.environ.get('RENODE_QUALIFIED') == '1' else [0xC0DEF407, 10, 10, 9, 4, 0]
assert values == expected, values
times = [float(x) for x in re.findall(r'^(0\.\d+)\s*$', run.stdout, re.M)]
assert len(times) == 2, times
assert abs(times[0] - 0.001) < 0.000002, times
assert abs(times[1] - 0.00025) < 0.000002, times
assert 'TimeElapsed = 00:00:00.012000000' in run.stdout
print(f'PASS: ELF boot marker, {values[1]} firmware IRQs, external PWM edges/timing, +4/-4 encoder feedback, 12 ms virtual time')
