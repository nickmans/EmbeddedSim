import os
from pathlib import Path
import re
import subprocess
import time

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent/'out'
OUT.mkdir(exist_ok=True)
RENODE=Path(os.environ.get('RENODE_ROOT','/workspace/tools/renode_1.17.0-portable'))
GCC=os.environ.get('ARM_GCC','/workspace/tools/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin/arm-none-eabi-gcc')
ENV=dict(os.environ,XDG_CONFIG_HOME='/workspace/.runtime-config',MPLCONFIGDIR='/workspace/.runtime-config/matplotlib')
os.environ.setdefault('MPLCONFIGDIR',ENV['MPLCONFIGDIR'])

def build(name,source,extra=()):
    elf=OUT/(name+'.elf')
    subprocess.run([GCC,'-mcpu=cortex-m4','-mthumb','-mfloat-abi=soft','-O1','-g',
        '-ffreestanding','-nostdlib','-Wl,--build-id=none',*extra,'-T',
        str(ROOT/'firmware/motor/link.ld'),str(ROOT/source),'-lm','-lc','-lgcc','-o',str(elf)],check=True)
    return elf

def prefix(sources=()):
    files=[ROOT/'emulation/renode/out'/n for n in ['QualifiedSTM32Timer.cs','QualifiedSTM32RCC.cs','STM32AFInput.cs']]
    files += [ROOT/p for p in sources]
    return [f'include @{p}' for p in files]+['mach create "robot"']

def execute(name,commands):
    warnings=OUT/(name+'.warnings.log'); warnings.unlink(missing_ok=True)
    script=OUT/(name+'.resc')
    script.write_text('\n'.join(['logLevel 3',f'logFile "{warnings}" true','logLevel 2 file']+commands+['quit'])+'\n')
    start=time.monotonic()
    p=subprocess.run([str(RENODE/'renode'),'--disable-gui','--console','--plain',str(script)],
        cwd=ROOT,env=ENV,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=300)
    (OUT/(name+'.log')).write_text(p.stdout)
    if p.returncode or re.search(r'\[ERROR\]|error CS|Errors during compilation|There was an error|No such command|Unhandled exception',p.stdout):
        raise RuntimeError(p.stdout[-8000:])
    assert warnings.exists() and not warnings.read_text().strip(),warnings.read_text()
    print(f'{name}: completed in {time.monotonic()-start:.1f}s',flush=True)
    return p.stdout.replace('\r','')
