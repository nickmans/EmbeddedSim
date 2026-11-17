using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using EmbeddedSim.Physics;
using Antmicro.Renode.Core;
namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class RobotPhysicsChecks : IGPIOReceiver
    {
        public void Reset(){}public void OnGPIO(int n,bool v){}
        private static void Require(bool p,string text){if(!p)throw new Exception(text);}
        public string Run(string path)
        {
            var rows=new List<string>{"kind,x_m,y_m,heading_rad,wl_rad_s,wr_rad_s,il_A,ir_A,energy_J,work_J,loss_J,residual_J,force_error"};
            DifferentialDrive straight=null,curve=null,mirror=null;
            foreach(string kind in new[] {"straight","inplace","reverse","curve","mirror","resistance","brake"}) {
                bool brake=kind=="brake";
                var m=brake?new DifferentialDrive(5,-3,.2,-.1):new DifferentialDrive();
                double initial=m.Energy, vl=3,vr=3,cr=0;
                if(kind=="inplace")vl=-3;
                if(kind=="reverse"){vl=-3;vr=-3;}
                if(kind=="curve"){vl=2;vr=4;}
                if(kind=="mirror"){vl=4;vr=2;}
                if(kind=="resistance")cr=.003;
                if(brake){vl=vr=0;cr=.0015;}
                int steps=kind=="curve"?200000:20000;
                double oldEnergy=initial,maxForce=0,oldX=0,oldY=0,oldYaw=0,oldAngleL=0,oldAngleR=0;
                for(int i=0;i<steps;i++) {
                    if(kind=="curve" && i==198000){oldX=m.X;oldY=m.Y;oldYaw=m.Heading;oldAngleL=m.Angle(0);oldAngleR=m.Angle(1);}
                    m.Step(vl,vr,0,cr,.0001);
                    if(brake)Require(m.Energy<=oldEnergy+1e-12,"unforced energy increased");
                    oldEnergy=m.Energy;
                    if(i%100==0){var f=m.Forces(0,cr);
                        double longitudinal=DifferentialDrive.Mass*DifferentialDrive.Radius*(f[0]+f[1])/2-(f[2]+f[3]);
                        double yaw=DifferentialDrive.YawInertia*DifferentialDrive.Radius*(f[1]-f[0])/DifferentialDrive.Track-DifferentialDrive.Track*(f[3]-f[2])/2;
                        maxForce=Math.Max(maxForce,Math.Max(Math.Abs(longitudinal),Math.Abs(yaw)));}
                }
                double loss=m.CopperLoss+m.MotorLoss+m.ExternalLoss;
                double residual=m.Energy-initial-m.Work+loss;
                Require(Math.Abs(residual)/(1+Math.Abs(initial)+Math.Abs(m.Work))<1e-5,"energy accounting failed");
                Require(maxForce<1e-8,"Newton force/torque consistency failed");
                if(kind=="straight") {straight=m;Require(Math.Abs(m.Y)<1e-10 && Math.Abs(m.Heading)<1e-10 && m.X>0,"straight symmetry");}
                if(kind=="reverse")Require(Math.Abs(m.Y)<1e-10 && Math.Abs(m.Heading)<1e-10 && m.X<0,"reverse geometry");
                if(kind=="inplace")Require(Math.Abs(m.X)+Math.Abs(m.Y)<1e-10 && m.Heading>0,"inplace geometry");
                if(kind=="curve") {
                    curve=m;double ds=.05*((m.Angle(0)-oldAngleL)+(m.Angle(1)-oldAngleR))/2;
                    double da=m.Heading-oldYaw, expectedK=2/.3/3;
                    Require(Math.Abs(da/ds/expectedK-1)<.001,"steady curvature");
                    double chord=Math.Sqrt((m.X-oldX)*(m.X-oldX)+(m.Y-oldY)*(m.Y-oldY));
                    Require(Math.Abs(chord/(2/expectedK*Math.Abs(Math.Sin(da/2)))-1)<.001,"arc geometry");
                }
                // Compare mirror runs for the same elapsed time, not curve's20 s.
                if(kind=="mirror")mirror=m;
                if(kind=="resistance")Require(m.Speed(1)<straight.Speed(1)-1 && m.Current(1)>straight.Current(1)+.01,"load not reflected electrically/mechanically");
                rows.Add(string.Join(",",new[]{kind,F(m.X),F(m.Y),F(m.Heading),F(m.Speed(0)),F(m.Speed(1)),F(m.Current(0)),F(m.Current(1)),F(m.Energy),F(m.Work),F(loss),F(residual),F(maxForce)}));
            }
            var other=new DifferentialDrive();for(int i=0;i<20000;i++)other.Step(2,4,0,0,.0001);
            Require(Math.Abs(other.X-mirror.X)<1e-10 && Math.Abs(other.Y+mirror.Y)<1e-10 && Math.Abs(other.Heading+mirror.Heading)<1e-10,"left/right mirror symmetry");
            var kick=new DifferentialDrive(il:1,ir:1);kick.Step(2,2,0,0,1e-6);
            double expected=.05/(DifferentialDrive.LocalJ+DifferentialDrive.Mass*.05*.05/2);
            Require(Math.Abs(kick.Speed(0)/1e-6/expected-1)<1e-5,"chassis inertia not coupled");
            var bridge=new SignedBridge();bridge.Pwm.Edge(0,true);
            Require(Math.Abs(bridge.Voltage(.001)+12)<1e-8,"reverse bridge voltage");
            bridge.Direction(.002,true);Require(bridge.Voltage(.003)==0 && bridge.UnsafeSwitches==1,"unsafe reversal not blanked");
            Require(Math.Abs(bridge.Voltage(.0041)-12)<1e-8,"forward bridge voltage");
            bridge.Pwm.Edge(.005,false);Require(Math.Abs(bridge.Voltage(.007))<1e-8,"zero duty not zero voltage");
            File.WriteAllLines(path,rows);return "PASS independent robot physics/energy/bridge";
        }
        private static string F(double x)=>x.ToString("R",CultureInfo.InvariantCulture);
    }
}
