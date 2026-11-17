"""Build real firmware, run Renode, assert predeclared thresholds, plot traces."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent/'out'
OUT.mkdir(parents=True,exist_ok=True)
RENODE=Path(os.environ.get('RENODE_ROOT','/workspace/tools/renode_1.17.0-portable'))
GCC=os.environ.get('ARM_GCC','/workspace/tools/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin/arm-none-eabi-gcc')
ENV=dict(os.environ,XDG_CONFIG_HOME='/workspace/.runtime-config',MPLCONFIGDIR='/workspace/.runtime-config/matplotlib')
os.environ.setdefault('MPLCONFIGDIR',ENV['MPLCONFIGDIR'])
parser=argparse.ArgumentParser(); parser.add_argument('--case',choices=['closed','open','reverse','repeat','pause','half','quarter','model','noload','antiwindup']); args=parser.parse_args()
(OUT/'results.json').unlink(missing_ok=True)
subprocess.run([sys.executable,str(ROOT/'emulation/renode/prepare.py')],check=True)

def prefix():
    sources=[ROOT/'emulation/renode/out'/name for name in ('QualifiedSTM32Timer.cs','QualifiedSTM32RCC.cs','STM32AFInput.cs')]
    sources += [ROOT/'models/Motor.cs',ROOT/'integration/renode/MotorLoop.cs',ROOT/'tests/closed_loop/ModelChecks.cs']
    return ['logLevel 3']+[f'include @{p}' for p in sources]+['mach create "motor"']

def run_renode(name,commands):
    script=OUT/(name+'.resc'); script.write_text('\n'.join(commands+['quit'])+'\n')
    start=time.monotonic()
    result=subprocess.run([str(RENODE/'renode'),'--disable-gui','--console','--plain',str(script)],
        env=ENV,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=240)
    (OUT/(name+'.log')).write_text(result.stdout)
    if result.returncode or re.search(r'\[ERROR\]|There was an error|No such command|Failed to|Unhandled exception|Errors during compilation|error CS',result.stdout):
        raise RuntimeError(result.stdout[-7000:])
    print(f'{name}: Renode completed in {time.monotonic()-start:.1f}s',flush=True)
    return result.stdout.replace('\r','')

def model_checks():
    path=OUT/'model.csv'; path.unlink(missing_ok=True)
    repl=ROOT/'emulation/renode/stm32f407vg.repl'
    out=run_renode('model',prefix()+[f'machine LoadPlatformDescription @{repl}',
        'machine LoadPlatformDescriptionFromString "checks: Miscellaneous.ModelChecks @ gpioPortA"',
        f'sysbus.gpioPortA.checks Run "{path}"'])
    assert 'PASS pure model' in out
    rows=list(csv.DictReader(path.open()))
    for row in rows:
        if row['kind']=='steady':
            voltage=float(row['voltage_V']); load=float(row['load_Nm'])
            expected=(.05*voltage/2-load)/(.0001+.05**2/2)
            current=(.0001*expected+load)/.05
            assert abs(float(row['speed_rad_s'])/expected-1)<1e-5
            assert abs(float(row['current_A'])/current-1)<1e-5
        if row['kind']=='brake': assert abs(float(row['speed_rad_s']))<1e-5
    transient=[r for r in rows if r['kind']=='transient']; ref=transient[-1]
    errors=[max(abs(float(r[k])-float(ref[k]))/scale for k,scale in [('current_A',1),('speed_rad_s',100),('angle_rad',1)]) for r in transient[:-1]]
    assert errors[0]>8*errors[1] and errors[1]>8*errors[2],errors
    return {'rk4_errors':errors,'steady_and_invariants':'passed'}

def scenario(name,mode,duration,step=25000,paused=False):
    elf=OUT/(name+'.elf')
    subprocess.run([GCC,'-mcpu=cortex-m4','-mthumb','-mfloat-abi=soft','-O1','-g','-ffreestanding',
        '-nostdlib','-Wl,--build-id=none',f'-DMODE={mode}','-T',str(ROOT/'firmware/motor/link.ld'),
        str(ROOT/'firmware/motor/controller.c'),'-lgcc','-o',str(elf)],check=True)
    platform=(ROOT/'emulation/renode/stm32f407vg.repl').read_text()
    platform+=f'''\nmotor: Miscellaneous.MotorLoop @ gpioPortA
    port: gpioPortA
    stepNanoseconds: {step}
    scenario: {mode}
    loadTorque: {'0.04' if mode==0 and name!='noload' else '0.0'}
gpioPortA:
    0 -> motor@0
'''
    repl=OUT/(name+'.repl'); repl.write_text(platform)
    commands=prefix()+[f'machine LoadPlatformDescription @{repl}',f'sysbus LoadELF @{elf}']
    if paused:
        commands+=['emulation RunFor "1.8"','echo "PAUSED_A"','sysbus.gpioPortA.motor Steps',
                   'sysbus.gpioPortA.motor Angle','echo "PAUSED_B"','sysbus.gpioPortA.motor Steps',
                   'sysbus.gpioPortA.motor Angle',f'emulation RunFor "{duration-1.8:.9f}"']
    else: commands += [f'emulation RunFor "{duration:.9f}"']
    trace=OUT/(name+'.csv'); trace.unlink(missing_ok=True)
    commands += [f'sysbus.gpioPortA.motor Finish "{trace}"','echo "COUNTER"','sysbus ReadDoubleWord 0x40000424',
        'echo "COUNT"','sysbus.gpioPortA.motor Count','echo "MAXEDGES"','sysbus.gpioPortA.motor MaxEdgesPerStep',
        'echo "MAXSTEP"','sysbus.gpioPortA.motor MaxStep',
        'echo "MAGIC"','sysbus ReadDoubleWord 0x20000000']
    output=run_renode(name,commands)
    assert '0xC0DEF407' in output,'firmware failed to boot'
    raw=int(re.search(r'COUNTER\s+0x([a-fA-F0-9]+)',output)[1],16)
    generated=int(re.search(r'COUNT\s+(-?(?:0x[0-9A-Fa-f]+|\d+))',output)[1],0)
    if generated>=2**63: generated-=2**64
    expected=((2 if mode==3 else 65530)+generated)&65535
    assert raw==expected,(name,raw,expected,generated)
    maxstep=float(re.search(r'MAXSTEP\s+([0-9.eE+-]+)',output)[1]); assert maxstep<step*1e-9+2e-9
    maxedges=int(re.search(r'MAXEDGES\s+(0x[0-9A-Fa-f]+|\d+)',output)[1],0)
    if mode==3: assert maxedges>=2,'reverse test must exercise multiple same-step GPIO edges'
    if paused:
        groups=re.search(r'PAUSED_A\s+(.+?)PAUSED_B\s+(.+?)COUNTER',output,re.S)
        # Compare the two read-only state samples; the latter also precedes
        # resumed execution output, but logLevel suppresses progress logging.
        first=groups[1].split(); second=groups[2].split()[:2]
        assert first==second,(first,second)
    return {'final_counter':raw,'generated_count':generated,'max_step_s':maxstep,'max_edges_per_step':maxedges,
            'firmware_sha256':hashlib.sha256(elf.read_bytes()).hexdigest(),
            'csv_sha256':hashlib.sha256(trace.read_bytes()).hexdigest()}

def load(name):
    import numpy as np
    return np.genfromtxt(OUT/(name+'.csv'),delimiter=',',names=True)

def check_closed(name):
    import numpy as np
    d=load(name); t=d['time_s']; metrics={}
    for start,end,target in [(.7,.85,60),(1.4,1.55,100),(2.2,2.35,100),(3,3.15,100)]:
        take=(t>=start)&(t<end)
        for column in ['model_speed_rad_s','estimated_speed_rad_s']:
            error=abs(float(np.mean(d[column][take]))-target)/target
            assert error<.02,(name,start,column,error)
            metrics[f'{start}_{column}_relative_error']=error
    assert max(d['model_speed_rad_s'][(t>=.1)&(t<.9)])<69
    assert max(d['model_speed_rad_s'][(t>=.9)&(t<1.6)])<115
    assert max(d['model_speed_rad_s'][(t>=2.4)&(t<3.2)])<115
    dip=float(min(d['model_speed_rad_s'][(t>=1.6)&(t<2.2)])); assert 80<dip<99,dip
    before=np.mean(d['measured_duty'][(t>=1.4)&(t<1.55)])
    after=np.mean(d['measured_duty'][(t>=2.2)&(t<2.35)])
    assert after-before>.10,(before,after)
    assert max(abs(d['model_speed_rad_s'][t>3.95]))<2
    assert min(d['commanded_duty'])>=0 and max(d['commanded_duty'])<=1
    assert min(d['measured_duty'])>=0 and max(d['measured_duty'])<=1
    assert max(d['irq_errors'])==0
    assert max(abs(d['encoder_count']-np.floor(d['angle_rad']*1024/(2*np.pi))))==0
    assert max(d['fw_total'])>20 and min(d['fw_counter'][d['fw_total']>10])<65530
    assert max(d['time_s']-d['fw_tick']*.001)<.0021
    # Check the stated 0.6 s settling budget as a band, not just a mean.
    for start,end,target,deadline in [(.1,.9,60,.7),(.9,1.6,100,1.5),(1.6,2.4,100,2.2),(2.4,3.2,100,3.0)]:
        for column in ['model_speed_rad_s','estimated_speed_rad_s']:
            bad=t[(t>=start)&(t<end)&(abs(d[column]-target)>.02*target)]
            settled=float(bad[-1]+.001) if len(bad) else start
            assert settled<=deadline,(name,start,column,settled,deadline)
            metrics[f'{start}_{column}_settled_at_s']=settled
    metrics.update(load_min_speed_rad_s=dip,unloaded_duty=float(before),loaded_duty=float(after))
    return metrics

def check_open():
    import numpy as np
    d=load('open'); t=d['time_s']
    for a,b,duty in [(.02,.09,0),(.11,.79,.5),(.81,.99,1),(1.01,1.99,0)]:
        assert max(abs(d['measured_duty'][(t>a)&(t<b)]-duty))<.002
    assert abs(d['model_speed_rad_s'][-1])<1
    assert max(d['irq_errors'])==0

def plot_results():
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for name in ['closed','open']:
        d=load(name); t=d['time_s']
        fig,ax=plt.subplots(5,1,figsize=(10,12),sharex=True)
        ax[0].plot(t,d['model_speed_rad_s'],label='model ground truth')
        ax[0].plot(t,d['estimated_speed_rad_s'],label='firmware encoder estimate',alpha=.7)
        ax[0].plot(t,d['setpoint_rad_s'],'--',label='firmware setpoint'); ax[0].set_ylabel('Speed (rad/s)'); ax[0].legend()
        ax[1].plot(t,d['measured_duty'],label='PA0 measured'); ax[1].plot(t,d['commanded_duty'],'--',label='firmware telemetry'); ax[1].set_ylabel('Duty (fraction)'); ax[1].legend()
        ax[2].plot(t,d['current_A'],label='armature'); ax[2].set_ylabel('Current (A)')
        ax[3].plot(t,d['load_Nm']); ax[3].set_ylabel('Load (N m)')
        ax[4].plot(t,d['encoder_count'],label='model encoder cumulative'); ax[4].plot(t,d['fw_total'],'--',label='firmware decoded total')
        ax[4].set_ylabel('Position (x4 counts)'); ax[4].legend(); ax[4].set_xlabel('Renode virtual time (s)')
        if name=='closed': ax[0].axvspan(1.6,2.4,color='gray',alpha=.15,label='load applied')
        for a in ax: a.grid(alpha=.25)
        fig.suptitle(name+' — illustrative averaged motor, not hardware validation')
        fig.tight_layout(); fig.savefig(OUT/(name+'.png'),dpi=150); plt.close(fig)
    loaded=load('closed'); unloaded=load('noload'); take=(loaded['time_s']>=1.4)&(loaded['time_s']<=3.2)
    t=loaded['time_s'][take]
    fig,ax=plt.subplots(3,1,figsize=(10,8),sharex=True)
    ax[0].plot(t,loaded['model_speed_rad_s'][take],label='loaded model')
    ax[0].plot(t,loaded['estimated_speed_rad_s'][take],label='firmware estimate',alpha=.7)
    ax[0].plot(t,unloaded['model_speed_rad_s'][take],'--',label='no-load counterfactual, identical ELF')
    ax[0].set_ylabel('Speed (rad/s)'); ax[0].legend()
    ax[1].plot(t,loaded['measured_duty'][take],label='loaded PA0 duty')
    ax[1].plot(t,unloaded['measured_duty'][take],'--',label='no-load PA0 duty'); ax[1].set_ylabel('Duty (fraction)'); ax[1].legend()
    ax[2].plot(t,loaded['load_Nm'][take]); ax[2].set_ylabel('Load (N m)'); ax[2].set_xlabel('Renode virtual time (s)')
    for a in ax: a.grid(alpha=.25); a.axvspan(1.6,2.4,color='gray',alpha=.12)
    fig.suptitle('External load response — illustrative motor, not hardware validation')
    fig.tight_layout(); fig.savefig(OUT/'load-response.png',dpi=150); plt.close(fig)

results={}
if args.case:
    if args.case=='model': results['model']=model_checks()
    else:
        name=args.case; mode=1 if name=='open' else (3 if name=='reverse' else (2 if name=='antiwindup' else 0))
        results[name]=scenario(name,mode,2 if mode in (1,2) else (1.5 if mode==3 else 4),
            12500 if name=='half' else (6250 if name=='quarter' else (250000 if mode==3 else 25000)),name=='pause')
        if mode==0 and name!='noload': results[name]['metrics']=check_closed(name)
        if mode==1: check_open()
else:
    results['model']=model_checks()
    for name,mode,duration,step,pause in [('open',1,2,25000,False),('closed',0,4,25000,False),
        ('reverse',3,1.5,250000,False),('repeat',0,4,25000,False),('pause',0,4,25000,True),
        ('half',0,4,12500,False),('quarter',0,4,6250,False),('noload',0,4,25000,False),('antiwindup',2,2,25000,False)]:
        results[name]=scenario(name,mode,duration,step,pause)
        if mode==0 and name!='noload': results[name]['metrics']=check_closed(name)
        if mode==1: check_open()
    assert results['closed']['csv_sha256']==results['repeat']['csv_sha256']==results['pause']['csv_sha256']
    reverse=load('reverse'); assert min(reverse['estimated_speed_rad_s'])<-5 and reverse['fw_total'][-1]<-20
    import numpy as np
    closed=load('closed'); noload=load('noload'); t=closed['time_s']
    assert results['closed']['firmware_sha256']==results['noload']['firmware_sha256']
    assert np.array_equal(closed[t<1.6-1e-9],noload[t<1.6-1e-9])
    for column in ['model_speed_rad_s','estimated_speed_rad_s']:
        take=(t>1.7)&(t<1.8)
        assert np.mean(noload[column][take]-closed[column][take])>1
    take=(t>2.2)&(t<2.35)
    assert np.mean(closed['commanded_duty'][take]-noload['commanded_duty'][take])>.1
    stress=load('antiwindup'); take=(stress['time_s']>1.7)&(stress['time_s']<1.9)
    assert max(stress['commanded_duty'])==1 and min(stress['commanded_duty'])>=0
    assert max(stress['integral'])<.95
    for col in ['model_speed_rad_s','estimated_speed_rad_s']: assert abs(np.mean(stress[col][take])-60)<1.2
    reference=load('quarter')['model_speed_rad_s']
    for name in ['closed','half']:
        error=load(name)['model_speed_rad_s']-reference
        results[name]['convergence']={'max_rad_s':float(max(abs(error))),'rms_rad_s':float(np.sqrt(np.mean(error**2)))}
        assert max(abs(error))<1 and np.sqrt(np.mean(error**2))<.25,results[name]['convergence']
    plot_results()
results['provenance']={
    'renode':subprocess.check_output([str(RENODE/'renode'),'--version'],env=ENV,text=True,timeout=10).strip(),
    'compiler':subprocess.check_output([GCC,'--version'],text=True,timeout=10).splitlines()[0],
    'sources_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [ROOT/'models/Motor.cs',ROOT/'integration/renode/MotorLoop.cs',ROOT/'firmware/motor/controller.c',
         ROOT/'docs/motor-loop-contract.md',ROOT/'emulation/renode/patches/0001-timer.patch',ROOT/'emulation/renode/patches/0002-rcc.patch']},
    'main_step_ns':25000,'refined_steps_ns':[12500,6250],'encoder_counts_per_revolution':1024,
    'status':'all requested checks for this invocation passed'
}
(OUT/'results.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2)); print('PASS selected motor-loop checks')
