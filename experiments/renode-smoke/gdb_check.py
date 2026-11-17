"""Verify a real GDB connection, firmware ISR breakpoint and single step."""
import os
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
renode = Path(os.environ.get('RENODE_ROOT', '/workspace/tools/renode_1.17.0-portable')) / 'renode'
gdb = os.environ.get('ARM_GDB', '/workspace/tools/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin/arm-none-eabi-gdb')
script = (HERE / 'out/smoke.resc').read_text().split('emulation RunFor')[0]
script += 'machine StartGdbServer 3333 true\n'
(HERE / 'out/gdb.resc').write_text(script)
with (HERE / 'out/gdb-server.log').open('w') as log:
    proc = subprocess.Popen([str(renode), '--disable-gui', '--port', '-1', '--plain',
                             str(HERE / 'out/gdb.resc')], stdout=log, stderr=log,
                            env=dict(os.environ, XDG_CONFIG_HOME='/workspace/.runtime-config'))
    try:
        for _ in range(100):
            if 'GDB server' in (HERE / 'out/gdb-server.log').read_text():
                break
            assert proc.poll() is None, 'Renode exited; see out/gdb-server.log'
            time.sleep(0.1)
        commands = ['target remote :3333', 'break tim4', 'continue',
                    'x/wx 0x20000000', 'info registers pc', 'stepi', 'detach']
        args = [gdb, '--batch', str(HERE / 'out/firmware.elf')]
        for cmd in commands:
            args += ['-ex', cmd]
        result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=30)
        (HERE / 'out/gdb-client.log').write_text(result.stdout)
        print(result.stdout)
        result.check_returncode()
        assert 'Breakpoint 1, tim4' in result.stdout
        assert '0xc0def407' in result.stdout
        assert 'Detaching from' in result.stdout or 'detached' in result.stdout
        print('PASS: GDB connected, hit firmware timer ISR, read RAM, single-stepped and detached')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
