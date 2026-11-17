using System;
using System.Collections.Generic;

namespace EmbeddedSim.Physics
{
    // Coherent SI units. Illustrative motor; no emulator dependencies.
    public class Motor
    {
        public const double R=2, L=.005, Ke=.05, Kt=.05, J=.0002, B=.0001;
        public Motor(double current=0, double speed=0, double angle=0)
        { Current=current; Speed=speed; Angle=angle; }
        public double Current { get; private set; }
        public double Speed { get; private set; }
        public double Angle { get; private set; }
        public static double CurrentRate(double current,double speed,double voltage)
        { return (voltage-R*current-Ke*speed)/L; }
        public static double Torque(double current) { return Kt*current; }
        private struct Rate { public double I,W,T; public Rate(double i,double w,double t) { I=i;W=w;T=t; } }
        private static Rate Derivative(double i,double w,double voltage,double load)
        { return new Rate(CurrentRate(i,w,voltage),(Torque(i)-B*w-load)/J,w); }
        public void Step(double voltage,double load,double dt)
        {
            if(dt<=0) throw new ArgumentOutOfRangeException(nameof(dt));
            var a=Derivative(Current,Speed,voltage,load);
            var b=Derivative(Current+dt*a.I/2,Speed+dt*a.W/2,voltage,load);
            var c=Derivative(Current+dt*b.I/2,Speed+dt*b.W/2,voltage,load);
            var d=Derivative(Current+dt*c.I,Speed+dt*c.W,voltage,load);
            Current+=dt*(a.I+2*b.I+2*c.I+d.I)/6;
            Speed+=dt*(a.W+2*b.W+2*c.W+d.W)/6;
            Angle+=dt*(a.T+2*b.T+2*c.T+d.T)/6;
        }
    }

    public class Quadrature
    {
        public const int CyclesPerRevolution=256, CountsPerRevolution=1024;
        public Quadrature(int resolution=CountsPerRevolution) { this.resolution=resolution; }
        private readonly int resolution;
        public long Count { get; private set; }
        public long Edges { get; private set; }
        public void Advance(double angle,Action<bool,bool> emit)
        {
            var target=(long)Math.Floor(angle*resolution/(2*Math.PI));
            while(Count!=target)
            {
                Count+=target>Count ? 1 : -1;
                var phase=(int)((Count%4+4)%4);
                var state=new[] {0,1,3,2}[phase];
                emit((state&1)!=0,(state&2)!=0);
                Edges++;
            }
        }
    }

    // Rolling high-time integration, including the present constant level.
    public class PwmWindow
    {
        public const double Window=.001;
        private struct Segment { public double Start,End; public bool High; }
        private readonly Queue<Segment> segments=new Queue<Segment>();
        private double lastEdge, lastRise=double.NaN, period;
        private bool high;
        public void Edge(double time,bool value)
        {
            if(time<lastEdge) throw new InvalidOperationException("Nonmonotonic PWM time");
            if(value==high) return;
            segments.Enqueue(new Segment {Start=lastEdge,End=time,High=high});
            if(value)
            {
                // The qualified carrier is 1 kHz. A long constant level ends
                // periodic tracking: require two fresh rises after resuming.
                period=!double.IsNaN(lastRise) && time>lastRise && time-lastRise<=2*Window
                    ? time-lastRise : 0;
                lastRise=time;
            }
            lastEdge=time; high=value;
        }
        public double Duty(double time)
        {
            double start=time-Window, total=0;
            while(segments.Count>0 && segments.Peek().End<=start) segments.Dequeue();
            foreach(var s in segments) if(s.High) total+=Math.Max(0,s.End-Math.Max(start,s.Start));
            if(high) total+=Math.Max(0,time-Math.Max(start,lastEdge));
            return Math.Max(0,Math.Min(1,total/Window));
        }
        public double Period(double time) { return time-lastEdge>2*Window ? 0 : period; }
    }
}
