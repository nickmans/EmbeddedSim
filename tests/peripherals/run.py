"""Compiled-firmware conformance suite. Stock mode deliberately fails.
All MCU MMIO is performed by firmware; host writes only the RAM mailbox.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'out'
TOOLS = Path('/workspace/tools')
RENODE = Path(os.environ.get('RENODE_ROOT', str(TOOLS / 'renode_1.17.0-portable')))
GCC = os.environ.get('ARM_GCC', str(TOOLS / 'xpack-arm-none-eabi-gcc-15.2.1-1.1/bin/arm-none-eabi-gcc'))
parser = argparse.ArgumentParser()
parser.add_argument('--stock', action='store_true')
args = parser.parse_args()
OUT = OUT / ('stock' if args.stock else 'patched')
OUT.mkdir(parents=True, exist_ok=True)
subprocess.run([GCC, '-mcpu=cortex-m4', '-mthumb', '-mfloat-abi=soft', '-O1', '-g',
                '-ffreestanding', '-nostdlib', '-Wl,--build-id=none', '-T',
                str(ROOT/'experiments/renode-smoke/link.ld'), str(HERE/'firmware.c'),
                '-o', str(OUT/'firmware.elf')], check=True)
qualified = not args.stock
if qualified:
    subprocess.run([sys.executable, str(ROOT/'emulation/renode/prepare.py')], check=True)

platform = (ROOT/'emulation/renode/stm32f407vg.repl').read_text()
if args.stock:
    platform = platform.replace('QualifiedSTM32Timer','STM32_Timer').replace('QualifiedSTM32RCC','STM32F4_RCC')
    platform = platform.replace(
        'systickClock: Miscellaneous.STM32F407SysTickClock @ sysbus\n    nvic: nvic\n', ''
    ).replace('    systickClock: systickClock\n', '')
    for i in (2,3,4):
        platform = platform.replace(f'    timer{i}: timer{i}\n','')
    platform = platform.split('encoder6:')[0]
    platform += 'gpioPortA:\n    6 -> timer3@0\n    7 -> timer3@1\n'
platform += 'probe: Miscellaneous.EventProbe @ gpioPortA\ngpioPortA:\n    0 -> probe@0\n'
(OUT/'platform.repl').write_text(platform)
warnings_path=OUT/'warnings.log'
warnings_path.unlink(missing_ok=True)
script = ['logLevel 3', f'logFile "{warnings_path}" true', 'logLevel 2 file']
if qualified:
    for name in ['QualifiedSTM32Timer.cs','QualifiedSTM32RCC.cs','STM32AFInput.cs']:
        script.append(f'include @{ROOT}/emulation/renode/out/{name}')
script += [f'include @{HERE}/EventProbe.cs', 'mach create "regression"',
           f'machine LoadPlatformDescription @{OUT}/platform.repl',
           f'sysbus LoadELF @{OUT}/firmware.elf', 'emulation RunFor "0.0001"']
seq = 0
checks = []
def advance(seconds): script.append(f'emulation RunFor "{seconds:.9f}"')
def cmd(op,*values):
    global seq
    seq+=1
    for i,v in enumerate([op,*values],3):
        script.append(f'sysbus WriteDoubleWord 0x{0x20000000+4*i:X} 0x{v:X}')
    script.append(f'sysbus WriteDoubleWord 0x20000004 {seq}')
    advance(.00005)
    script.extend([f'echo "ACK {seq}"', 'sysbus ReadDoubleWord 0x20000008'])
def snap(name):
    for key,command in [('trace','sysbus.gpioPortA.probe Trace'),('state','sysbus.gpioPortA.probe State'),
                         ('enc','sysbus ReadDoubleWord 0x20000028'),('irq','sysbus ReadDoubleWord 0x2000002C'),
                         ('bad','sysbus ReadDoubleWord 0x20000030'),('cleared','sysbus ReadDoubleWord 0x20000034'),
                         ('cnt','sysbus ReadDoubleWord 0x20000038'),('ugflag','sysbus ReadDoubleWord 0x2000003C')]:
        script.extend([f'echo "MARK {name}.{key}"', command])
def clear(): script.append('sysbus.gpioPortA.probe Clear')
def cycle(forward=True):
    for p,v in ([(6,1),(7,1),(6,0),(7,0)] if forward else [(7,1),(6,1),(7,0),(6,0)]):
        script.append(f'sysbus.gpioPortA OnGPIO {p} {"true" if v else "false"}')
        advance(.000002)
def pwm(name,psc,arr,ccr,freq=16000000,flags=0):
    cmd(1,psc,arr,ccr,flags)
    period=(psc+1)*(arr+1)/freq
    advance(period*2); clear(); advance(period*5); snap(name)
    checks.append((name,lambda data,n=name,p=period,h=(psc+1)*ccr/freq: check_pwm(data,n,p,h)))

for i,(psc,arr,ccr) in enumerate([(15,999,250),(0,1599,800),(7,1999,1500),(31,999,100)]):
    pwm(f'pwm{i}',psc,arr,ccr)
    pwm(f'pwm_preloaded{i}',psc,arr,ccr,flags=3)
for ccr,state in [(0,False),(1000,True),(1200,True)]:
    cmd(1,15,999,ccr,0); advance(.002); clear(); advance(.002); name=f'constant{ccr}'; snap(name)
    checks.append((name,lambda d,n=name,s=state: require(not events(d,n) and boolean(d,n)==s, f'{n}: expected constant {s}')))
# Correct and wrong output AF/mode; preserve timer operation.
pwm('pwm_for_gpio',15,999,250)
for pin,mode,af,name in [(0,0,1,'pwm_input_mode'),(0,2,0,'pwm_wrong_af')]:
    cmd(5,pin,mode,af); clear(); advance(.003); snap(name)
    checks.append((name,lambda d,n=name: require(not events(d,n), f'{n}: output leaked through mux')))
cmd(5,0,2,1); advance(.002); clear(); advance(.005); snap('pwm_af_restored')
checks.append(('pwm_af_restored',lambda d: check_pwm(d,'pwm_af_restored',.001,.00025)))

cmd(2,0,65535); cycle(); snap('enc_forward'); cycle(False); snap('enc_reverse')
cmd(3,0); cycle(); snap('enc_disabled'); cmd(3,1); cycle(); snap('enc_reenabled')
for n,value in [('enc_forward',4),('enc_reverse',0),('enc_disabled',0),('enc_reenabled',4)]:
    checks.append((n,lambda d,n=n,v=value: require(integer(d,n,'enc')==v,f'{n}: expected {v}, got {integer(d,n,"enc")}')))
cmd(2,0,65535); cmd(8,2,0); cycle(); snap('enc_clock_gated'); cmd(8,2,2); cycle(); snap('enc_clock_resumed')
for n,v in [('enc_clock_gated',0),('enc_clock_resumed',4)]:
    checks.append((n,lambda d,n=n,v=v: require(integer(d,n,'enc')==v,f'{n}: expected {v}')))
cmd(9,2); cycle(); snap('enc_reset'); cmd(2,0,65535); cycle(); snap('enc_reset_reinit')
for n,v in [('enc_reset',0),('enc_reset_reinit',4)]:
    checks.append((n,lambda d,n=n,v=v: require(integer(d,n,'enc')==v,f'{n}: expected {v}')))
wrap_start=len(script)
cmd(2,65534,65535); cycle(); snap('enc_wrap'); cycle(False); snap('enc_underflow')
wrap_script=script[wrap_start:]
del script[wrap_start:]
for n,value in [('enc_wrap',2),('enc_underflow',65534)]:
    checks.append((n,lambda d,n=n,v=value: require(integer(d,n,'enc')==v,f'{n}: expected {v}, got {integer(d,n,"enc")}')))
for mode,af,name in [(0,2,'enc_input_mode'),(2,0,'enc_wrong_af')]:
    cmd(2,0,65535); cmd(5,6,mode,af); cmd(5,7,mode,af); cycle(); snap(name)
    checks.append((name,lambda d,n=name: require(integer(d,n,'enc')==0,f'{n}: count changed')))
cmd(5,6,2,2); cmd(5,7,2,2); cmd(2,0,65535); cycle(); snap('enc_af_restored')
checks.append(('enc_af_restored',lambda d: require(integer(d,'enc_af_restored','enc')==4,'encoder restore failed')))
# Buffered PSC, ARR and CCR: capture full cycles spanning a firmware write.
for offset,value,newperiod,newhigh,name in [(0x28,31,.002,.0005,'psc_buffer'),(0x2C,1999,.002,.00025,'arr_buffer'),(0x34,750,.001,.00075,'ccr_buffer')]:
    cmd(1,15,999,250,3); advance(.002); clear(); advance(.0023); cmd(7,offset,value); advance(.007); snap(name)
    checks.append((name,lambda d,n=name,p=newperiod,h=newhigh: check_transition(d,n,p,h)))
# UG must transfer shadows before restart, including PSC and ARR.
cmd(1,15,999,250,3); cmd(7,0,128); cmd(7,0x28,31); cmd(7,0x2C,1999); cmd(7,0x34,750); cmd(7,0x14,1)
clear(); cmd(7,0,129); advance(.002); snap('ug_first_cycle'); advance(.014); snap('ug_transfer')
checks.append(('ug_first_cycle',lambda d: require(1000<=integer(d,'ug_first_cycle','cnt')<=1030,'UG did not load PSC/ARR before the first cycle')))
checks.append(('ug_transfer',lambda d: check_pwm(d,'ug_transfer',.004,.0015)))
# IRQ count deltas use settled snapshots, not boot/initialization boundaries.
cmd(6,15,999); advance(.002); snap('irq0'); advance(.008); snap('irq1')
cmd(10,0); snap('irq_stopped0'); advance(.004); snap('irq_stopped1'); cmd(10,1); snap('irq_resume0'); advance(.004); snap('irq_resume1')
for n,a,b,count in [('irq_periodic','irq0','irq1',8),('irq_stopped','irq_stopped0','irq_stopped1',0),('irq_resumed','irq_resume0','irq_resume1',4)]:
    checks.append((n,lambda d,a=a,b=b,c=count: check_irq(d,a,b,c)))
cmd(8,4,0); snap('irq_gate0'); advance(.004); snap('irq_gate1'); cmd(8,4,4); snap('irq_gate2'); advance(.004); snap('irq_gate3')
checks.append(('irq_clock_gated',lambda d: check_irq(d,'irq_gate0','irq_gate1',0)))
checks.append(('irq_clock_resumed',lambda d: check_irq(d,'irq_gate2','irq_gate3',4)))
cmd(9,4); snap('irq_reset0'); advance(.004); snap('irq_reset1')
checks.append(('irq_reset',lambda d: check_irq(d,'irq_reset0','irq_reset1',0)))
cmd(11); snap('ug_uif')
checks.append(('ug_uif_without_uie',lambda d: require(integer(d,'ug_uif','ugflag')==1,'UG must set UIF independently of UIE')))
# Clock-source changes are all done by firmware, with ready/status polling.
for name,source,hpre,ppre,freq in [('hsi_div1',0,0,0,16000000),('hsi_apb2',0,0,4,16000000),('hsi_apb4',0,0,5,8000000),('hsi_ahb2_apb4',0,8,5,4000000),('hse8',1,0,0,8000000),('pll168_apb4',2,0,5,84000000),('pll168_apb8',2,0,6,42000000)]:
    cmd(4,source,hpre,ppre); pwm(name,7,999,250,freq)
    # TIM4 periodic interrupts at each supported clock point.
    cmd(6,int(freq/1000000)-1,999); advance(.002); snap(name+'irq0'); advance(.004); snap(name+'irq1')
    checks.append((name+'_irq',lambda d,n=name: check_irq(d,n+'irq0',n+'irq1',4)))
# Reconfigure a RUNNING timer clock; no host frequency rewriting or reinit.
cmd(4,0,0,0); cmd(1,15,999,250,3); advance(.003); cmd(4,0,0,5); advance(.004); clear(); advance(.01); snap('running_clock_change')
checks.append(('running_clock_change',lambda d: check_pwm(d,'running_clock_change',.002,.0005)))
# APB1 enable gate freezes timer clocks and resumes them.
cmd(8,1,0); clear(); advance(.005); snap('pwm_clock_gated'); cmd(8,1,1); advance(.004); clear(); advance(.01); snap('pwm_clock_resumed')
checks.append(('pwm_clock_gated',lambda d: require(not events(d,'pwm_clock_gated'),'clock-gated PWM continued')))
checks.append(('pwm_clock_resumed',lambda d: check_pwm(d,'pwm_clock_resumed',.002,.0005)))
# Stock has a fatal counter-underflow bug: run wrap last so independent checks
# still produce evidence. Re-number ACKs in the moved block and following script.
script += wrap_script
ack_seq=0
for i,line in enumerate(script):
    if line.startswith('sysbus WriteDoubleWord 0x20000004 '):
        ack_seq+=1; script[i]=f'sysbus WriteDoubleWord 0x20000004 {ack_seq}'
    elif line.startswith('echo "ACK '): script[i]=f'echo "ACK {ack_seq}"'
script += ['echo "BOOTMARK"','sysbus ReadDoubleWord 0x20000000','quit']
(OUT/'regression.resc').write_text('\n'.join(script)+'\n')

def require(condition,message):
    if not condition: raise AssertionError(message)
def events(data,name):
    return [(float(t),int(s)) for t,s in re.findall(r'(\d+\.\d+(?:[Ee][-+]?\d+)?|\d+[Ee][-+]?\d+):([01])',data[name+'.trace'])]
def integer(data,name,key): return int(re.search(r'0x([A-Fa-f0-9]+)',data[name+'.'+key])[1],16)
def boolean(data,name): return 'True' in data[name+'.state']
def timings(data,name):
    ev=events(data,name)
    rising=[t for t,s in ev if s]
    periods=[b-a for a,b in zip(rising,rising[1:])]
    high=[b-a for (a,s),(b,z) in zip(ev,ev[1:]) if s and not z]
    return periods,high
def check_pwm(data,name,period,high):
    periods,highs=timings(data,name)
    require(len(periods)>=3 and len(highs)>=3,f'{name}: insufficient edges')
    # Renode time domain is nanoseconds; accept rounding, never a whole counter tick.
    require(all(abs(p-period)<2.1e-9 for p in periods),f'{name}: periods {periods}, expected {period}')
    require(all(abs(h-high)<2.1e-9 for h in highs),f'{name}: high times {highs}, expected {high}')
def check_transition(data,name,period,high):
    periods,highs=timings(data,name)
    require(len(periods)>=3 and len(highs)>=3,f'{name}: insufficient edges')
    for xs,old,new in [(periods,.001,period),(highs,.00025,high)]:
        require(all(min(abs(x-old),abs(x-new))<2.1e-9 for x in xs),f'{name}: mixed/broken cycle {xs}')
        require(abs(xs[0]-old)<2.1e-9 and abs(xs[-1]-new)<2.1e-9,f'{name}: shadow not transferred {xs}')
        if abs(old-new)>1e-12:
            # Clear at <50 us into a settled cycle, record 2.3 ms, then
            # firmware writes (<50 us). The third recorded rise is the next
            # UEV: exactly two complete old pulses/periods must precede it.
            require(len(xs)>=3 and all(abs(x-old)<2.1e-9 for x in xs[:2])
                    and all(abs(x-new)<2.1e-9 for x in xs[2:]),
                    f'{name}: transfer was not at the first following UEV: {xs}')
def check_irq(data,a,b,count):
    delta=integer(data,b,'irq')-integer(data,a,'irq')
    require(delta==count,f'{a}/{b}: IRQ delta {delta}, expected {count}')
    require(integer(data,b,'bad')==0 and integer(data,b,'cleared')==0,f'{b}: ISR flags/clear failure')

label='stock' if args.stock else 'patched'
run=subprocess.run([str(RENODE/'renode'),'--disable-gui','--console','--plain',str(OUT/'regression.resc')],
                    cwd=ROOT,env=dict(os.environ,XDG_CONFIG_HOME='/workspace/.runtime-config'),
                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
(OUT/f'{label}.log').write_text(run.stdout)
clean=re.sub(r'^.*\[(?:INFO|WARNING)\].*$', '',run.stdout,flags=re.M).replace('\r','')
parts=re.split(r'^MARK (\S+)\s*\n',clean,flags=re.M)
data=dict(zip(parts[1::2],parts[2::2]))
results=[]
try:
    require(run.returncode==0,f'Renode exit {run.returncode}')
    require(not re.search(r'\[ERROR\]|No such command|There was an error|Failed to|unhandled|Unhandled',run.stdout),'Monitor/model error; see log')
    if qualified:
        require(warnings_path.exists(),'warning log missing')
        # Renode accepts/stores FLASH cache enable tags but does not model CPU
        # caches. Keep realistic firmware writes and retain these explicit warnings.
        allowed='flash_controller: Unhandled write to offset 0x0. Unhandled bits: [8-10] when writing value 0x705. Tags: PRFTEN (0x1), ICEN (0x1), DCEN (0x1).'
        unexpected=[line for line in warnings_path.read_text().splitlines() if not line.endswith(allowed)]
        require(not unexpected,'unexpected model warning/unimplemented access; see warnings.log')
    require('0xC0DEF407' in clean,'firmware boot marker missing/faulted')
    acks=re.findall(r'ACK (\d+)\s+0x([0-9A-Fa-f]+)',clean)
    require(len(acks)==seq and all(int(a)==int(b,16) for a,b in acks),f'mailbox timeout: {len(acks)}/{seq} acknowledgements')
except AssertionError as exc:
    results.append({'name':'emulator_completed','passed':False,'error':str(exc)})
    print(str(exc))
for name,check in checks:
    try: check(data); result={'name':name,'passed':True}
    except (AssertionError,KeyError,TypeError) as exc: result={'name':name,'passed':False,'error':str(exc)}
    results.append(result); print(('PASS ' if result['passed'] else 'FAIL ')+name+(' — '+result['error'] if 'error' in result else ''))
def version(command):
    return subprocess.check_output(command, env=dict(os.environ,XDG_CONFIG_HOME='/workspace/.runtime-config'),
                                   text=True, timeout=10).strip()
trace_payload={key:events(data,key[:-6]) for key in data if key.endswith('.trace')}
summary={'profile':label,'checks':results,'passed':sum(r['passed'] for r in results),'total':len(results),
         'renode':version([str(RENODE/'renode'),'--version']),
         'compiler':version([GCC,'--version']).splitlines()[0],
         'renode_source':'ab721d88e135a1bcb8ed2ecc5a38f51cbe61fdd2',
         'infrastructure_source':'066a7f13c052215632d469c995c89aea37c573b1',
         'firmware_sha256':hashlib.sha256((OUT/'firmware.elf').read_bytes()).hexdigest(),
         'trace_sha256':hashlib.sha256(json.dumps(trace_payload,sort_keys=True).encode()).hexdigest()}
if qualified:
    summary['compiled_source_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'emulation/renode/out').glob('Qualified*.cs')}
(OUT/f'{label}.json').write_text(json.dumps(summary,indent=2)+'\n')
print(f'{summary["passed"]}/{len(results)} passed ({label}); logs in {OUT}')
sys.exit(0 if all(r['passed'] for r in results) else 1)
