import argparse
import hashlib
import json
import re
import subprocess
import sys
import numpy as np
from common import ROOT,OUT,RENODE,ENV,build,prefix,execute

parser=argparse.ArgumentParser();parser.add_argument('--case',choices=['main','repeat','pause','half','quarter','noload','physics']);args=parser.parse_args()
subprocess.run([sys.executable,str(ROOT/'emulation/renode/prepare.py')],check=True)
sources=['models/Motor.cs','models/DifferentialDrive.cs','integration/renode/RobotLoop.cs','tests/robot/PhysicsChecks.cs']
(OUT/'results.json').unlink(missing_ok=True)

def physics():
    path=OUT/'physics.csv';path.unlink(missing_ok=True)
    output=execute('physics',prefix(sources)+[f'machine LoadPlatformDescription @{ROOT}/emulation/renode/stm32f407vg-robot.repl',
        'machine LoadPlatformDescriptionFromString "checks: Miscellaneous.RobotPhysicsChecks @ gpioPortA"',f'sysbus.gpioPortA.checks Run "{path}"'])
    assert 'PASS independent robot physics' in output
    return {'status':'passed','csv_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def load(name):return np.genfromtxt(OUT/(name+'.csv'),delimiter=',',names=True)
def angle_error(a,b):return np.arctan2(np.sin(a-b),np.cos(a-b))

def check_trace(name):
    d=load(name);t=d['time_s'];metrics={}
    position=np.hypot(d['x_m']-d['odom_x_m'],d['y_m']-d['odom_y_m'])
    heading=abs(angle_error(d['heading_rad'],d['odom_heading_rad']))
    assert max(position)<.02,(name,max(position));assert max(heading)<.02,(name,max(heading))
    for start,end,refs in [(1.7,1.95,(10,10)),(4.1,4.35,(-5,5)),(6.7,6.95,(6,10)),(9.3,9.55,(-8,-8))]:
        take=(t>=start)&(t<end)
        for i,side in enumerate('lr'):
            error=abs(np.mean(d['w'+side+'_rad_s'][take])-refs[i])/abs(refs[i])
            assert error<.05,(name,start,side,error)
            metrics[f'{start}_{side}_mean_speed_error']=float(error)
    for end in (2.8,5.2,7.8,10.4):
        take=(t>end-.05)&(t<end)
        assert max(abs(d['wl_rad_s'][take]))<.5 and max(abs(d['wr_rad_s'][take]))<.5,(name,'stop',end)
    assert min(d['duty_l'])>=0 and max(d['duty_l'])<=1 and min(d['duty_r'])>=0 and max(d['duty_r'])<=1
    assert max(d['unsafe_switches'])==0 and max(d['irq_errors'])==0
    for side in 'lr':
        encoder=d['encoder_'+side];fw=d['fw_total_'+side]
        assert max(abs(encoder-fw))<50 # observer age <=1ms, speeds below40 rad/s
    assert max(d['time_s']-d['fw_tick']*.001)<.0021
    metrics.update(max_position_error_m=float(max(position)),max_heading_error_rad=float(max(heading)))
    return metrics

def scenario(name):
    step=12500 if name=='half' else 6250 if name=='quarter' else 25000
    elf=build('robot','firmware/robot/controller.c')
    repl=(ROOT/'emulation/renode/stm32f407vg-robot.repl').read_text()+f'''\nrobotBody: Miscellaneous.RobotLoop @ gpioPortA
    portA: gpioPortA
    portB: gpioPortB
    stepNanoseconds: {step}
    rightResistance: {'0.0' if name=='noload' else '0.0015'}
gpioPortA:
    0 -> robotBody@0
    1 -> robotBody@1
    4 -> robotBody@2
    5 -> robotBody@3
'''
    path=OUT/(name+'.repl');path.write_text(repl)
    s=prefix(sources)+[f'machine LoadPlatformDescription @{path}',f'sysbus LoadELF @{elf}']
    if name=='pause':
        s+=['emulation RunFor "3.6"','echo "STATE_A"','sysbus.gpioPortA.robotBody Steps','sysbus.gpioPortA.robotBody X',
            'echo "STATE_B"','sysbus.gpioPortA.robotBody Steps','sysbus.gpioPortA.robotBody X','emulation RunFor "6.8"']
    else:s+=['emulation RunFor "10.4"']
    trace=OUT/(name+'.csv');trace.unlink(missing_ok=True)
    s+=[f'sysbus.gpioPortA.robotBody Finish "{trace}"','echo "LEFT"','sysbus ReadDoubleWord 0x40000424',
        'echo "RIGHT"','sysbus ReadDoubleWord 0x40000824','echo "LC"','sysbus.gpioPortA.robotBody LeftCount',
        'echo "RC"','sysbus.gpioPortA.robotBody RightCount','echo "MAXSTEP"','sysbus.gpioPortA.robotBody MaxStep',
        'echo "MAGIC"','sysbus ReadDoubleWord 0x20000000']
    output=execute(name,s);assert '0xC0DEF407' in output
    result={'step_ns':step,'elf_sha256':hashlib.sha256(elf.read_bytes()).hexdigest()}
    for tag,offset,counttag in [('LEFT',65530,'LC'),('RIGHT',2,'RC')]:
        raw=int(re.search(tag+r'\s+0x([0-9A-Fa-f]+)',output)[1],16)
        count=int(re.search(counttag+r'\s+(-?(?:0x[0-9A-Fa-f]+|\d+))',output)[1],0)
        if count>=2**63:count-=2**64
        assert raw==(offset+count)&65535,(tag,raw,count)
        result[tag.lower()+'_count']=count
    maximum=float(re.search(r'MAXSTEP\s+([0-9Ee.+-]+)',output)[1]);assert maximum<step*1e-9+2e-9
    if name=='pause':
        part=re.search(r'STATE_A\s+(.+?)STATE_B\s+(.+?)LEFT',output,re.S)
        assert part[1].split()==part[2].split()[:2]
    result['max_step_s']=maximum;result['csv_sha256']=hashlib.sha256(trace.read_bytes()).hexdigest()
    result['metrics']=check_trace(name)
    return result


results={}
if args.case:
    results[args.case]=physics() if args.case=='physics' else scenario(args.case)
else:
    results['physics']=physics()
    for name in ['main','repeat','pause','half','quarter','noload']:results[name]=scenario(name)
    assert results['main']['csv_sha256']==results['repeat']['csv_sha256']==results['pause']['csv_sha256']
    main=load('main');other=load('noload');t=main['time_s']
    assert results['main']['elf_sha256']==results['noload']['elf_sha256']
    assert np.array_equal(main[t<.8-1e-9],other[t<.8-1e-9])
    take=(t>1.1)&(t<1.35)
    assert np.mean(main['ir_A'][take]-other['ir_A'][take])>.1
    assert np.mean(main['duty_r'][take]-other['duty_r'][take])>.02
    take=(t>.85)&(t<1.1)
    assert np.mean(other['wr_rad_s'][take]-main['wr_rad_s'][take])>.1
    assert np.mean(other['estimate_r_rad_s'][take]-main['estimate_r_rad_s'][take])>.1
    reference=load('quarter')
    for name in ['main','half']:
        d=load(name);pe=np.hypot(d['x_m']-reference['x_m'],d['y_m']-reference['y_m'])
        he=abs(angle_error(d['heading_rad'],reference['heading_rad']))
        we=np.maximum(abs(d['wl_rad_s']-reference['wl_rad_s']),abs(d['wr_rad_s']-reference['wr_rad_s']))
        assert max(pe)<.005 and max(he)<.01 and max(we)<.5,(name,max(pe),max(he),max(we))
        results[name]['convergence']={'position_max_m':float(max(pe)),'heading_max_rad':float(max(he)),'wheel_speed_max_rad_s':float(max(we))}
    from plots import render
    render()
results['provenance']={'sources':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
    [ROOT/s for s in sources]+[ROOT/'firmware/robot/controller.c',ROOT/'firmware/robot/hardware.h',ROOT/'docs/robot-contract.md']},
    'renode':subprocess.check_output([str(RENODE/'renode'),'--version'],env=ENV,text=True,timeout=10).strip()}
(OUT/'results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2));print('PASS selected robot checks')
