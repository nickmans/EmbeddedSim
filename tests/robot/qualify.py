"""Qualify added hardware paths with compiled firmware before robot runs."""
import json
import re
import subprocess
import sys
from common import ROOT,OUT,build,prefix,execute

subprocess.run([sys.executable,str(ROOT/'emulation/renode/prepare.py')],check=True)
elf=build('qualify','firmware/robot/qualify.c')
repl=(ROOT/'emulation/renode/stm32f407vg-robot.repl').read_text()
for i,pin in enumerate([0,1,4,5]):
    repl+=f'probe{i}: Miscellaneous.EventProbe @ gpioPortA\ngpioPortA:\n    {pin} -> probe{i}@0\n'
(OUT/'qualify.repl').write_text(repl)
s=prefix(['tests/peripherals/EventProbe.cs'])+[f'machine LoadPlatformDescription @{OUT}/qualify.repl',
    f'sysbus LoadELF @{elf}','emulation RunFor "0.003"']
seq=0; checks=[]
def wait(t):s.append(f'emulation RunFor "{t:.9f}"')
def command(op,a=0,b=0):
    global seq
    seq+=1
    for i,v in enumerate([op,a,b],3):s.append(f'sysbus WriteDoubleWord 0x{0x20000000+4*i:X} {v}')
    s.append(f'sysbus WriteDoubleWord 0x20000004 {seq}');wait(.00005)
    s.extend([f'echo "ACK {seq}"','sysbus ReadDoubleWord 0x20000008'])
def snapshot(name):
    for i in range(4):
        for key in ['Trace','State']:s.extend([f'echo "MARK {name}.p{i}{key}"',f'sysbus.gpioPortA.probe{i} {key}'])
    for key,index in [('l',8),('r',9),('irq',10),('bad',11)]:
        s.extend([f'echo "MARK {name}.{key}"',f'sysbus ReadDoubleWord 0x{0x20000000+index*4:X}'])
def clear():
    for i in range(4):s.append(f'sysbus.gpioPortA.probe{i} Clear')
def cycle(side,forward=True):
    port='gpioPortA' if side==0 else 'gpioPortB'
    for pin,value in ([(6,1),(7,1),(6,0),(7,0)] if forward else [(7,1),(6,1),(7,0),(6,0)]):
        s.append(f'sysbus.{port} OnGPIO {pin} {"true" if value else "false"}');wait(.000002)
def number(d,key):return int(re.search(r'0x([0-9A-Fa-f]+)',d[key])[1],16)
def trace(d,key):return [(float(t),int(b)) for t,b in re.findall(r'([\d.Ee+-]+):([01])',d[key])]
def pwm(d,name,i,high):
    ev=trace(d,f'{name}.p{i}Trace');r=[t for t,b in ev if b]
    periods=[b-a for a,b in zip(r,r[1:])]
    highs=[b-a for (a,v),(b,z) in zip(ev,ev[1:]) if v and not z]
    assert len(periods)>=3 and len(highs)>=3
    assert all(abs(p-.001)<2.1e-9 for p in periods),periods
    assert all(abs(h-high)<2.1e-9 for h in highs),highs
def equal(d,name,l,r):assert (number(d,name+'.l'),number(d,name+'.r'))==(l,r),name
clear();wait(.005);snapshot('baseline')
checks += [('left PWM',lambda d:pwm(d,'baseline',0,.00025)),('right PWM',lambda d:pwm(d,'baseline',1,.00075))]
command(1,750,250);wait(.003);clear();wait(.005);snapshot('swap')
checks += [('left CCR update',lambda d:pwm(d,'swap',0,.00075)),('right CCR update',lambda d:pwm(d,'swap',1,.00025))]
command(1,0,1000);wait(.003);clear();wait(.003);snapshot('constant')
def constant(d):
    assert not trace(d,'constant.p0Trace') and 'False' in d['constant.p0State']
    assert not trace(d,'constant.p1Trace') and 'True' in d['constant.p1State']
checks.append(('0/100 percent independent',constant))
command(1,250,750);wait(.003);command(5,0);clear();wait(.005);snapshot('af0')
def af(d):
    pwm(d,'af0',0,.00025); assert not trace(d,'af0.p1Trace')
checks.append(('PA1 wrong AF disconnects only right PWM',af))
command(5,1);wait(.003);clear();wait(.005);snapshot('af1')
checks.append(('PA1 AF1 restored',lambda d:pwm(d,'af1',1,.00075)))
cycle(0);snapshot('left');checks.append(('left wrap, right independent',lambda d:equal(d,'left',2,2)))
cycle(1,False);snapshot('right');checks.append(('right underflow, left independent',lambda d:equal(d,'right',2,65534)))
command(2,1);cycle(1);snapshot('disabled');checks.append(('TIM4 encoder CEN=0',lambda d:equal(d,'disabled',2,65534)))
command(2,3);cycle(1);snapshot('enabled');checks.append(('TIM4 reenable/wrap',lambda d:equal(d,'enabled',2,2)))
cycle(0,False);snapshot('left_reverse');checks.append(('TIM3 reverse underflow',lambda d:equal(d,'left_reverse',65534,2)))
cycle(0);command(4,2,0);cycle(1);snapshot('bad_af');checks.append(('PB6/7 AF gating',lambda d:equal(d,'bad_af',2,2)))
command(4,0,2);cycle(1);snapshot('bad_mode');checks.append(('PB6/7 mode gating',lambda d:equal(d,'bad_mode',2,2)))
command(4,2,2);cycle(1);snapshot('restore');checks.append(('PB6/7 restored',lambda d:equal(d,'restore',2,6)))
command(7,0);cycle(0);cycle(1);snapshot('gate');checks.append(('TIM4 gate independent of TIM3',lambda d:equal(d,'gate',6,6)))
command(7,1);cycle(1,False);snapshot('ungate');checks.append(('TIM4 clock resume',lambda d:equal(d,'ungate',6,2)))
for levels in [0,1,2,3]:
    command(6,levels);snapshot(f'dir{levels}')
    def direction(d,levels=levels):
        assert ('True' in d[f'dir{levels}.p2State'])==bool(levels&1)
        assert ('True' in d[f'dir{levels}.p3State'])==bool(levels&2)
    checks.append((f'PA4/5 BSRR levels {levels}',direction))
snapshot('irq0');wait(.008);snapshot('irq1')
def irq(d): assert number(d,'irq1.irq')-number(d,'irq0.irq')==8 and number(d,'irq1.bad')==0
checks.append(('TIM2 update IRQ28 delivery/clear/continue',irq))
s+=['echo "MAGIC"','sysbus ReadDoubleWord 0x20000000']
out=execute('qualify',s)
assert '0xC0DEF407' in out
acks=re.findall(r'ACK (\d+)\s+0x([0-9A-Fa-f]+)',out)
assert len(acks)==seq and all(int(a)==int(b,16) for a,b in acks)
parts=re.split(r'^MARK (\S+)\s*\n',out,flags=re.M); data=dict(zip(parts[1::2],parts[2::2]))
results=[]
for name,check in checks:
    try:check(data);results.append({'name':name,'passed':True});print('PASS',name)
    except Exception as e:results.append({'name':name,'passed':False,'error':str(e)});print('FAIL',name,str(e))
(OUT/'qualification.json').write_text(json.dumps(results,indent=2)+'\n')
assert all(r['passed'] for r in results)
print(f'{len(results)}/{len(results)} robot hardware checks passed')
