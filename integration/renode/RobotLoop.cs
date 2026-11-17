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
    public class RobotLoop : IGPIOReceiver
    {
        public RobotLoop(IMachine machine,STM32_GPIOPort portA,STM32_GPIOPort portB,
            uint stepNanoseconds=25000,double rightResistance=.0015)
        {
            this.machine=machine;ports=new[] {portA,portB};this.stepNanoseconds=stepNanoseconds;
            this.rightResistance=rightResistance;bus=machine.SystemBus;
            timer=new LimitTimer(machine.ClockSource,1000000000,this,"robot-physics",limit:stepNanoseconds,
                direction:Direction.Ascending,eventEnabled:true);
            timer.LimitReached+=Tick;Reset();
        }
        public void Reset()
        {
            timer.Reset();model=new DifferentialDrive();
            enc=new[] {new Quadrature(4096),new Quadrature(4096)};
            bridge=new[] {new SignedBridge(),new SignedBridge()}; levels=new bool[2,2];
            voltage=new double[2];telemetry=new uint[22];
            time=machine.ClockSource.CurrentValue.TotalSeconds;nextSample=machine.ClockSource.CurrentValue.Ticks+1000000;
            resistance=0;Steps=0;MaxStep=0;rows.Clear();
            rows.Add("time_s,x_m,y_m,heading_rad,odom_x_m,odom_y_m,odom_heading_rad,fw_tick,wl_rad_s,wr_rad_s,il_A,ir_A,estimate_l_rad_s,estimate_r_rad_s,reference_l_rad_s,reference_r_rad_s,duty_l,duty_r,dir_l,dir_r,voltage_l_V,voltage_r_V,encoder_l,encoder_r,fw_total_l,fw_total_r,fw_counter_l,fw_counter_r,resistance_l_Nm,resistance_r_Nm,right_drag_Nms,energy_J,work_J,copper_J,motor_loss_J,resistance_loss_J,unsafe_switches,irq_errors");
            timer.Enabled=true;
        }
        public void OnGPIO(int number,bool value)
        {
            var now=machine.ClockSource.CurrentValue.TotalSeconds;
            if(number<2)bridge[number].Pwm.Edge(now,value);
            else bridge[number-2].Direction(now,value);
        }
        private void Tick()
        {
            var now=machine.ClockSource.CurrentValue.TotalSeconds;double dt=now-time;
            if(dt<=0 || dt>stepNanoseconds*1e-9+2e-9)throw new Exception("robot time bound exceeded");
            Steps++;MaxStep=Math.Max(dt,MaxStep);
            model.Step(voltage[0],voltage[1],0,resistance,dt);
            for(int wheel=0;wheel<2;wheel++) {
                int side=wheel;
                enc[side].Advance(model.Angle(side),(a,b)=> {
                    if(levels[side,0]!=a)ports[side].OnGPIO(6,a);
                    if(levels[side,1]!=b)ports[side].OnGPIO(7,b);
                    levels[side,0]=a;levels[side,1]=b;
                });
            }
            time=now;
            resistance=now>=.8-1e-12 && now<1.4-1e-12 ? rightResistance : 0;
            voltage[0]=bridge[0].Voltage(now);voltage[1]=bridge[1].Voltage(now);
            if(machine.ClockSource.CurrentValue.Ticks>=nextSample) {
                nextSample+=1000000;
                var bank=bus.ReadDoubleWord(0x20000100);
                if(bank>1)throw new Exception("invalid telemetry bank");
                for(uint i=0;i<22;i++)telemetry[i]=bus.ReadDoubleWord(0x20000000+128*bank+4*i);
                rows.Add(string.Join(",",new[] {
                    F(now),F(model.X),F(model.Y),F(model.Heading),FF(12),FF(13),FF(14),telemetry[1].ToString(),
                    F(model.Speed(0)),F(model.Speed(1)),F(model.Current(0)),F(model.Current(1)),FF(4),FF(5),FF(2),FF(3),
                    F(bridge[0].Pwm.Duty(now)),F(bridge[1].Pwm.Duty(now)),bridge[0].Forward?"1":"-1",bridge[1].Forward?"1":"-1",
                    F(voltage[0]),F(voltage[1]),enc[0].Count.ToString(),enc[1].Count.ToString(),
                    ((int)telemetry[8]).ToString(),((int)telemetry[9]).ToString(),telemetry[10].ToString(),telemetry[11].ToString(),
                    "0",F(resistance*model.Speed(1)),F(resistance),F(model.Energy),F(model.Work),F(model.CopperLoss),
                    F(model.MotorLoss),F(model.ExternalLoss),UnsafeSwitches.ToString(),telemetry[17].ToString()
                }));
            }
        }
        public void Finish(string path) { timer.Enabled=false;File.WriteAllLines(path,rows); }
        public long LeftCount => enc[0].Count;public long RightCount => enc[1].Count;
        public int UnsafeSwitches=>bridge[0].UnsafeSwitches+bridge[1].UnsafeSwitches;
        public long Steps {get;private set;}public double MaxStep {get;private set;}
        public double X=>model.X;public double Heading=>model.Heading;
        private string FF(int index)=>F(BitConverter.ToSingle(BitConverter.GetBytes(telemetry[index]),0));
        private static string F(double v)=>v.ToString("R",CultureInfo.InvariantCulture);
        private readonly IMachine machine;private readonly STM32_GPIOPort[] ports;private readonly IBusController bus;
        private readonly LimitTimer timer;private readonly uint stepNanoseconds;private readonly double rightResistance;
        private DifferentialDrive model;private Quadrature[] enc;private SignedBridge[] bridge;
        private bool[,] levels;private double[] voltage;private uint[] telemetry;
        private double time,resistance;private ulong nextSample;private readonly List<string> rows=new List<string>();
    }
}
