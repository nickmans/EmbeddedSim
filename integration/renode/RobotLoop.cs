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
        public RobotLoop(IMachine machine, STM32_GPIOPort portA, STM32_GPIOPort portB,
            uint stepNanoseconds=25000, bool exampleObserver=false)
        {
            this.machine=machine;
            ports=new[] {portA,portB};
            encoderOutput=new Action<bool,bool>[] {(a,b)=>EncoderOutput(0,a,b),(a,b)=>EncoderOutput(1,a,b)};
            this.stepNanoseconds=stepNanoseconds;
            bus=machine.SystemBus;
            observer=exampleObserver ? new ExampleRobotObserver(bus) : null;
            timer=new LimitTimer(machine.ClockSource,1000000000,this,"robot-physics",limit:stepNanoseconds,
                direction:Direction.Ascending,eventEnabled:true);
            timer.LimitReached+=Tick;
            Reset();
        }

        public void ConfigureBody(string mass, string yawInertia, string radius, string track, string wheelInertia)
        {
            this.mass=Parse(mass);this.yawInertia=Parse(yawInertia);this.radius=Parse(radius);
            this.track=Parse(track);this.wheelInertia=Parse(wheelInertia);
            recordGeometry=true;
            Reset();
        }

        public void SetInitialPose(string x, string y, string yaw)
        {
            startX=Parse(x);startY=Parse(y);startYaw=Parse(yaw);
            Reset();
        }

        // Each route denotes a complete qualified A/B pair. -1 leaves it physically disconnected.
        public void SetEncoderRoutes(int left, int right)
        {
            encoderRoutes[0]=left;encoderRoutes[1]=right;
        }

        public void AddLoad(string start, string end, string left, string right)
        {
            loads.Add(new Load { Start=Parse(start), End=Parse(end), Left=Parse(left), Right=Parse(right) });
        }

        public void Reset()
        {
            timer.Reset();
            model=new DifferentialDrive(mass:mass,yawInertia:yawInertia,radius:radius,track:track,
                wheelJ:wheelInertia,x:startX,y:startY,heading:startYaw);
            enc=new[] {new Quadrature(4096),new Quadrature(4096)};
            bridge=new[] {new SignedBridge(),new SignedBridge()};
            physicalLevels=new bool[4];
            deliveredLevels=new bool[4];
            physicalEdges=new long[4];
            deliveredEdges=new long[4];
            liveLevels=new[] {-1,-1,-1,-1};
            forcedLevels=new[] {-1,-1,-1,-1};
            voltage=new double[2];
            time=machine.ClockSource.CurrentValue.TotalSeconds;
            nextSample=machine.ClockSource.CurrentValue.Ticks+1000000;
            leftDrag=rightDrag=0;
            liveRightDrag=null;
            Steps=0;MaxStep=0;
            observer?.Reset();
            rows.Clear();
            rows.Add("time_s,x_m,y_m,heading_rad"
                +(observer==null ? "" : ",odom_x_m,odom_y_m,odom_heading_rad,fw_tick")
                +",wl_rad_s,wr_rad_s,il_A,ir_A"
                +(observer==null ? "" : ",estimate_l_rad_s,estimate_r_rad_s,reference_l_rad_s,reference_r_rad_s")
                +",duty_l,duty_r,dir_l,dir_r,voltage_l_V,voltage_r_V,encoder_l,encoder_r"
                +(observer==null ? "" : ",fw_total_l,fw_total_r,fw_counter_l,fw_counter_r")
                +",resistance_l_Nm,resistance_r_Nm,right_drag_Nms,energy_J,work_J,copper_J,motor_loss_J,resistance_loss_J,unsafe_switches"
                +(observer==null ? "" : ",irq_errors")
                +(recordGeometry ? ",wheel_radius_m,track_width_m,left_drag_Nms,tim3_counter,tim4_counter" : ""));
            if(encoderEvidence) AppendEncoderHeaders();
            timer.Enabled=true;
        }

        public void OnGPIO(int number, bool value)
        {
            var now=machine.ClockSource.CurrentValue.TotalSeconds;
            if(number<2) bridge[number].Pwm.Edge(now,value);
            else bridge[number-2].Direction(now,value);
        }

        private void Tick()
        {
            var now=machine.ClockSource.CurrentValue.TotalSeconds;
            var dt=now-time;
            if(dt<=0 || dt>stepNanoseconds*1e-9+2e-9) throw new Exception("robot time bound exceeded");
            Steps++;MaxStep=Math.Max(dt,MaxStep);
            model.Step(voltage[0],voltage[1],leftDrag,rightDrag,dt);
            if(encoderFaults.Count!=0) RefreshEncoderFaults(machine.ClockSource.CurrentValue.Ticks);
            for(int wheel=0;wheel<2;wheel++)
                enc[wheel].Advance(model.Angle(wheel),encoderOutput[wheel]);
            time=now;
            leftDrag=rightDrag=0;
            foreach(var load in loads)
            {
                if(now>=load.Start-1e-12 && now<load.End-1e-12)
                {
                    leftDrag+=load.Left;rightDrag+=load.Right;
                }
            }
            if(liveRightDrag.HasValue) rightDrag=liveRightDrag.Value;
            voltage[0]=bridge[0].Voltage(now);voltage[1]=bridge[1].Voltage(now);
            if(machine.ClockSource.CurrentValue.Ticks>=nextSample)
            {
                nextSample+=1000000;
                Record(now);
            }
        }

        private void EncoderOutput(int side, bool a, bool b)
        {
            PhysicalEncoderLevel(2*side,a);
            PhysicalEncoderLevel(2*side+1,b);
        }

        private void PhysicalEncoderLevel(int channel, bool level)
        {
            if(physicalLevels[channel]==level) return;
            physicalLevels[channel]=level;
            physicalEdges[channel]++;
            DeliverEncoderLevel(channel);
        }

        private void DeliverEncoderLevel(int channel)
        {
            int route=encoderRoutes[channel/2];
            if(route<0) return;
            int forced=forcedLevels[channel];
            bool level=forced<0 ? physicalLevels[channel] : forced!=0;
            if(deliveredLevels[channel]==level) return;
            ports[route].OnGPIO(6+channel%2,level);
            deliveredLevels[channel]=level;
            deliveredEdges[channel]++;
        }

        public void EnableEncoderEvidence()
        {
            if(encoderEvidence) return;
            if(Steps!=0) throw new InvalidOperationException("Enable encoder evidence before execution.");
            encoderEvidence=true;
            AppendEncoderHeaders();
        }

        public void AddEncoderFault(int channel, int level, ulong start, ulong end)
        {
            encoderFaults.Add(new EncoderFault { Channel=channel, Level=level, Start=start, End=end });
        }

        public void InitializeEncoderFaults() => RefreshEncoderFaults(machine.ClockSource.CurrentValue.Ticks);

        public void SetLiveEncoderFault(int channel, int level)
        {
            if(!encoderEvidence || channel<0 || channel>=4 || level< -1 || level>1)
                throw new ArgumentOutOfRangeException(nameof(channel));
            liveLevels[channel]=level;
            RefreshEncoderFaults(machine.ClockSource.CurrentValue.Ticks);
        }

        private void RefreshEncoderFaults(ulong now)
        {
            for(int channel=0;channel<4;channel++)
            {
                int level=liveLevels[channel];
                if(level<0)
                    foreach(var fault in encoderFaults)
                        if(fault.Channel==channel && fault.Start<=now && now<fault.End)
                        {
                            level=fault.Level;
                            break;
                        }
                if(forcedLevels[channel]==level) continue;
                forcedLevels[channel]=level;
                DeliverEncoderLevel(channel);
            }
        }

        private void AppendEncoderHeaders()
        {
            foreach(var channel in EncoderNames)
                rows[0]+=$",enc_{channel}_physical_edges,enc_{channel}_delivered_edges,enc_{channel}_physical_level,enc_{channel}_delivered_level,enc_{channel}_forced_level";
        }

        private void Record(double now)
        {
            observer?.Read();
            var fields=new List<string> {F(now),F(model.X),F(model.Y),F(model.Heading)};
            observer?.AddPose(fields);
            fields.AddRange(new[] {F(model.Speed(0)),F(model.Speed(1)),F(model.Current(0)),F(model.Current(1))});
            observer?.AddSpeeds(fields);
            fields.AddRange(new[] {F(bridge[0].Pwm.Duty(now)),F(bridge[1].Pwm.Duty(now)),
                bridge[0].Forward?"1":"-1",bridge[1].Forward?"1":"-1",F(voltage[0]),F(voltage[1]),
                enc[0].Count.ToString(),enc[1].Count.ToString()});
            observer?.AddCounts(fields);
            fields.AddRange(new[] {leftDrag==0 ? "0" : F(leftDrag*model.Speed(0)),F(rightDrag*model.Speed(1)),
                F(rightDrag),F(model.Energy),F(model.Work),F(model.CopperLoss),F(model.MotorLoss),
                F(model.ExternalLoss),UnsafeSwitches.ToString()});
            observer?.AddErrors(fields);
            if(recordGeometry) fields.AddRange(new[] {F(radius),F(track),F(leftDrag),
                bus.ReadDoubleWord(0x40000424).ToString(),bus.ReadDoubleWord(0x40000824).ToString()});
            if(encoderEvidence)
                for(int channel=0;channel<4;channel++)
                {
                    fields.Add(physicalEdges[channel].ToString());
                    fields.Add(deliveredEdges[channel].ToString());
                    fields.Add(physicalLevels[channel]?"1":"0");
                    fields.Add(deliveredLevels[channel]?"1":"0");
                    fields.Add(forcedLevels[channel].ToString());
                }
            rows.Add(string.Join(",",fields));
        }

        // Live commands are issued only while Renode is paused between RunFor calls.
        // The preceding interval and its recording remain intact.
        public void SetLiveRightDrag(string value)
        {
            var drag=Parse(value);
            if(double.IsNaN(drag) || drag<0 || drag>0.02)
                throw new ArgumentOutOfRangeException(nameof(value));
            liveRightDrag=rightDrag=drag;
        }

        public void ExportLive(string path, int firstSample)
        {
            using(var output=new StreamWriter(path))
            {
                output.WriteLine(machine.ClockSource.CurrentValue.Ticks.ToString(CultureInfo.InvariantCulture));
                output.WriteLine(rows[0]);
                for(var index=firstSample+1;index<rows.Count;index++) output.WriteLine(rows[index]);
            }
        }

        public void Finish(string path)
        {
            timer.Enabled=false;
            if(observer!=null && !observer.Seen) throw new InvalidOperationException("Example observer never received the EmbeddedSim frame signature. Disable it for other firmware.");
            File.WriteAllLines(path,rows);
        }

        public long LeftCount => enc[0].Count;
        public long RightCount => enc[1].Count;
        public int UnsafeSwitches => bridge[0].UnsafeSwitches+bridge[1].UnsafeSwitches;
        public long Steps {get;private set;}
        public double MaxStep {get;private set;}
        public double X => model.X;
        public double Heading => model.Heading;
        // Unquoted Monitor decimals can be narrowed before method argument conversion.
        private static double Parse(string value) => double.Parse(value,CultureInfo.InvariantCulture);
        internal static string F(double v) => v.ToString("R",CultureInfo.InvariantCulture);

        private struct Load { public double Start,End,Left,Right; }
        private readonly List<Load> loads=new List<Load>();
        private readonly IMachine machine;
        private readonly STM32_GPIOPort[] ports;
        private readonly ExampleRobotObserver observer;
        private readonly IBusController bus;
        private readonly LimitTimer timer;
        private readonly uint stepNanoseconds;
        private readonly Action<bool,bool>[] encoderOutput;
        private readonly int[] encoderRoutes={0,1};
        private double mass=DifferentialDrive.Mass, yawInertia=DifferentialDrive.YawInertia,
            radius=DifferentialDrive.Radius, track=DifferentialDrive.Track, wheelInertia=DifferentialDrive.WheelJ;
        private double startX,startY,startYaw;
        private bool recordGeometry;
        private DifferentialDrive model;
        private Quadrature[] enc;
        private SignedBridge[] bridge;
        private struct EncoderFault { public int Channel,Level; public ulong Start,End; }
        private readonly List<EncoderFault> encoderFaults=new List<EncoderFault>();
        private static readonly string[] EncoderNames={"left_a","left_b","right_a","right_b"};
        private bool encoderEvidence;
        private bool[] physicalLevels,deliveredLevels;
        private long[] physicalEdges,deliveredEdges;
        private int[] liveLevels,forcedLevels;
        private double[] voltage;
        private double time,leftDrag,rightDrag;
        private double? liveRightDrag;
        private ulong nextSample;
        private readonly List<string> rows=new List<string>();
    }

    internal sealed class ExampleRobotObserver
    {
        public ExampleRobotObserver(IBusController bus) { this.bus=bus; }
        public bool Seen { get; private set; }
        public void Reset() { Seen=false; }

        public void Read()
        {
            var bank=bus.ReadDoubleWord(0x20000100);
            if(bank>1) throw new InvalidOperationException("Invalid EmbeddedSim example telemetry bank. Disable the observer for other firmware.");
            uint address=0x20000000+128*bank;
            var signature=bus.ReadDoubleWord(address);
            if(signature!=0xC0DEF407)
                throw new InvalidOperationException("Invalid EmbeddedSim example telemetry signature. Disable the observer for other firmware.");
            Seen=true;
            for(uint i=1;i<words.Length;i++) words[i]=bus.ReadDoubleWord(address+4*i);
        }

        public void AddPose(List<string> fields) => fields.AddRange(new[] {Float(12),Float(13),Float(14),words[1].ToString()});
        public void AddSpeeds(List<string> fields) => fields.AddRange(new[] {Float(4),Float(5),Float(2),Float(3)});
        public void AddCounts(List<string> fields) => fields.AddRange(new[] {
            ((int)words[8]).ToString(),((int)words[9]).ToString(),words[10].ToString(),words[11].ToString()});
        public void AddErrors(List<string> fields) => fields.Add(words[17].ToString());
        private string Float(int i) => RobotLoop.F(BitConverter.ToSingle(BitConverter.GetBytes(words[i]),0));
        private readonly IBusController bus;
        private readonly uint[] words=new uint[22];
    }
}
