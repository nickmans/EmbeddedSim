using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using EmbeddedSim.Physics;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.GPIOPort;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    // One-way observer of firmware telemetry. Only PWM and external load drive
    // physics. Only GPIO A/B signals feed the MCU. No host CNT writes.
    public class MotorLoop : IGPIOReceiver
    {
        public MotorLoop(IMachine machine, STM32_GPIOPort port, uint stepNanoseconds=25000, int scenario=0,
            double loadTorque=.04, double loadOn=1.6, double loadOff=2.4)
        {
            this.machine=machine; this.port=port; this.scenario=scenario;
            this.stepNanoseconds=stepNanoseconds; bus=machine.SystemBus;
            this.loadTorque=loadTorque; this.loadOn=loadOn; this.loadOff=loadOff;
            timer=new LimitTimer(machine.ClockSource,1000000000,this,"physics",
                limit:stepNanoseconds,direction:Direction.Ascending,eventEnabled:true);
            timer.LimitReached+=Tick;
            Reset();
        }
        public void Reset()
        {
            timer.Reset(); motor=new Motor(); encoder=new Quadrature(); pwm=new PwmWindow();
            time=machine.ClockSource.CurrentValue.TotalSeconds; voltage=load=0;
            nextSample=time+.001; a=b=reverseStarted=false; Steps=0; MaxStep=0; MaxEdgesPerStep=0;
            frames.Clear(); telemetry=new uint[11];
            frames.Add("time_s,fw_tick,setpoint_rad_s,model_speed_rad_s,estimated_speed_rad_s,measured_duty,commanded_duty,current_A,load_Nm,angle_rad,encoder_count,encoder_edges,fw_total,fw_counter,integral,pwm_period_s,irq_errors");
            timer.Enabled=true;
        }
        public void OnGPIO(int number,bool value)
        { pwm.Edge(machine.ClockSource.CurrentValue.TotalSeconds,value); }
        private void Tick()
        {
            var now=machine.ClockSource.CurrentValue.TotalSeconds;
            var dt=now-time;
            if(dt<=0 || dt>stepNanoseconds*1e-9+2e-9)
                throw new InvalidOperationException("Physics scheduling bound exceeded");
            MaxStep=Math.Max(MaxStep,dt); Steps++;
            // Advance ONLY with inputs known at the previous boundary.
            motor.Step(voltage,load,dt);
            if(scenario==3 && !reverseStarted && now>=.05-1e-12)
            { motor=new Motor(speed:-40); reverseStarted=true; } // external shaft impulse
            var before=encoder.Edges;
            encoder.Advance(motor.Angle,(newA,newB)=> {
                if(a!=newA) port.OnGPIO(6,newA);
                if(b!=newB) port.OnGPIO(7,newB);
                a=newA; b=newB;
            });
            MaxEdgesPerStep=Math.Max(MaxEdgesPerStep,encoder.Edges-before);
            // Crossings are delivered at this boundary, never backdated. Their
            // delay relative to continuous angle crossing is bounded by dt.
            time=now;
            var duty=pwm.Duty(now);
            voltage=12*duty; // ideal synchronous forward bridge; V=0 is braking
            load=now>=loadOn-1e-12 && now<loadOff-1e-12 ? loadTorque : 0;
            if(now+1e-12>=nextSample)
            {
                nextSample+=.001;
                // Seqlock: never export a partially written firmware frame.
                var seq=bus.ReadDoubleWord(0x20000028);
                if((seq&1)==0)
                    for(uint i=0;i<11;i++) telemetry[i]=bus.ReadDoubleWord(0x20000000+4*i);
                frames.Add(string.Join(",",new[] {
                    F(now),telemetry[1].ToString(),F(Float(telemetry[2])),F(motor.Speed),
                    F(Float(telemetry[3])),F(duty),F(Float(telemetry[4])),F(motor.Current),
                    F(load),F(motor.Angle),encoder.Count.ToString(),encoder.Edges.ToString(),
                    ((int)telemetry[5]).ToString(),telemetry[6].ToString(),F(Float(telemetry[8])),
                    F(pwm.Period(now)),telemetry[9].ToString()
                }));
            }
        }
        public void Finish(string path) { timer.Enabled=false; File.WriteAllLines(path,frames); }
        public long Count => encoder.Count;
        public long Edges => encoder.Edges;
        public long Steps { get; private set; }
        public long MaxEdgesPerStep { get; private set; }
        public double MaxStep { get; private set; }
        public double Speed => motor.Speed;
        public double Angle => motor.Angle;
        private static string F(double value) => value.ToString("R",CultureInfo.InvariantCulture);
        private static float Float(uint bits) => BitConverter.ToSingle(BitConverter.GetBytes(bits),0);
        private Motor motor;
        private Quadrature encoder;
        private PwmWindow pwm;
        private readonly IMachine machine;
        private readonly STM32_GPIOPort port;
        private readonly IBusController bus;
        private readonly LimitTimer timer;
        private readonly uint stepNanoseconds;
        private readonly int scenario;
        private readonly List<string> frames=new List<string>();
        private uint[] telemetry;
        private double time,nextSample,voltage,load;
        private readonly double loadTorque,loadOn,loadOff;
        private bool a,b,reverseStarted;
    }
}
