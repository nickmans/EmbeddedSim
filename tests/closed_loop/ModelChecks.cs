using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using EmbeddedSim.Physics;
using Antmicro.Renode.Core;
namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class ModelChecks : IGPIOReceiver
    {
        public void Reset() {}
        public void OnGPIO(int number,bool value) {}
        private static void Require(bool good,string message) { if(!good) throw new Exception(message); }
        public string Run(string path)
        {
            var rows=new List<string> {"kind,dt_s,voltage_V,load_Nm,current_A,speed_rad_s,angle_rad"};
            foreach(double load in new[] {0,.04})
            {
                var m=new Motor(); for(int i=0;i<200000;i++) m.Step(6,load,.000025);
                rows.Add(Row("steady",.000025,6,load,m));
            }
            foreach(double h in new[] {.001,.0005,.00025,.000015625})
            {
                var m=new Motor(); for(int i=0;i<(int)Math.Round(.1/h);i++) m.Step(6,.04,h);
                rows.Add(Row("transient",h,6,.04,m));
            }
            var brake=new Motor(speed:100);
            double energy=.5*Motor.L*brake.Current*brake.Current+.5*Motor.J*brake.Speed*brake.Speed;
            for(int i=0;i<200000;i++)
            {
                brake.Step(0,0,.000025);
                var next=.5*Motor.L*brake.Current*brake.Current+.5*Motor.J*brake.Speed*brake.Speed;
                Require(next<=energy+1e-12,"braking generated energy"); energy=next;
            }
            rows.Add(Row("brake",.000025,0,0,brake));
            var q=new Quadrature(); int oldState=0; long emitted=0;
            Action<bool,bool> edge=(a,b)=> { int state=(a?1:0)|(b?2:0); int bits=state^oldState;
                Require(bits==1 || bits==2,"invalid quadrature jump");oldState=state;emitted++; };
            foreach(double position in new[] {10.25,-6.75,65540.25,65531.25})
            {
                q.Advance(position*2*Math.PI/1024,edge);
                Require(q.Count==(long)Math.Floor(position),"fraction/reverse/multiple-edge count loss");
            }
            Require(emitted==q.Edges && emitted>65536,"quadrature edges discarded");
            var pwm=new PwmWindow(); Require(pwm.Duty(0)==0,"startup duty");
            pwm.Edge(0,true); Require(Math.Abs(pwm.Duty(.0005)-.5)<1e-12,"startup high window");
            Require(Math.Abs(pwm.Duty(10)-1)<1e-9 && pwm.Period(10)==0,"constant high became stale");
            pwm.Edge(10,false); Require(pwm.Duty(10.01)==0,"constant low left stale drive");
            pwm.Edge(10.02,true); Require(pwm.Period(10.02)==0,"stale period after restart");
            pwm.Edge(10.02025,false); pwm.Edge(10.021,true);
            Require(Math.Abs(pwm.Period(10.021)-.001)<1e-9,"period not reacquired from fresh edges");
            File.WriteAllLines(path,rows);
            return "PASS pure model, braking energy, quadrature and PWM invariants";
        }
        private static string Row(string kind,double h,double v,double load,Motor m)
        {
            return string.Join(",",new[] {kind,F(h),F(v),F(load),F(m.Current),F(m.Speed),F(m.Angle)});
        }
        private static string F(double value) => value.ToString("R",CultureInfo.InvariantCulture);
    }
}
