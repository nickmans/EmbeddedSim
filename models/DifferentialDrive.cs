using System;
namespace EmbeddedSim.Physics
{
    // Direct drive; masses/inertias and conventions are derived in robot-contract.md.
    public class DifferentialDrive
    {
        public const double Mass=2, YawInertia=.04, Radius=.05, Track=.30, WheelJ=.00005;
        public const double LocalJ=Motor.J+WheelJ;
        private readonly double mass, yawInertia, radius, track, localJ, a, c;
        // iL,iR,wL,wR,thetaL,thetaR,x,y,yaw,work,copper,motor loss,external loss.
        private double[] s=new double[13];
        public DifferentialDrive(double wl=0,double wr=0,double il=0,double ir=0,
            double mass=Mass,double yawInertia=YawInertia,double radius=Radius,double track=Track,
            double wheelJ=WheelJ,double x=0,double y=0,double heading=0)
        {
            this.mass=mass;this.yawInertia=yawInertia;this.radius=radius;this.track=track;
            localJ=Motor.J+wheelJ;
            a=localJ+mass*radius*radius/4+yawInertia*radius*radius/(track*track);
            c=mass*radius*radius/4-yawInertia*radius*radius/(track*track);
            s[0]=il;s[1]=ir;s[2]=wl;s[3]=wr;s[6]=x;s[7]=y;s[8]=heading;
        }
        public double Current(int side) => s[side];
        public double Speed(int side) => s[2+side];
        public double Angle(int side) => s[4+side];
        public double X => s[6]; public double Y => s[7]; public double Heading => s[8];
        public double V => radius*(s[2]+s[3])/2;
        public double YawRate => radius*(s[3]-s[2])/track;
        public double Energy => Motor.L*(s[0]*s[0]+s[1]*s[1])/2
            +localJ*(s[2]*s[2]+s[3]*s[3])/2+mass*V*V/2+yawInertia*YawRate*YawRate/2;
        public double Work => s[9]; public double CopperLoss=>s[10];
        public double MotorLoss=>s[11]; public double ExternalLoss=>s[12];
        private double[] Accelerations(double il,double ir,double wl,double wr,double cl,double cr)
        {
            double ql=Motor.Torque(il)-(Motor.B+cl)*wl;
            double qr=Motor.Torque(ir)-(Motor.B+cr)*wr;
            return new[] {(a*ql-c*qr)/(a*a-c*c),(a*qr-c*ql)/(a*a-c*c)};
        }
        public double[] Forces(double cl,double cr)
        {
            var acc=Accelerations(s[0],s[1],s[2],s[3],cl,cr);
            return new[] {acc[0],acc[1],
                (Motor.Torque(s[0])-(Motor.B+cl)*s[2]-localJ*acc[0])/radius,
                (Motor.Torque(s[1])-(Motor.B+cr)*s[3]-localJ*acc[1])/radius};
        }
        private double[] Rate(double[] y,double vl,double vr,double cl,double cr)
        {
            var acc=Accelerations(y[0],y[1],y[2],y[3],cl,cr);
            double v=radius*(y[2]+y[3])/2, yawRate=radius*(y[3]-y[2])/track;
            return new[] {Motor.CurrentRate(y[0],y[2],vl),Motor.CurrentRate(y[1],y[3],vr),
                acc[0],acc[1],y[2],y[3],v*Math.Cos(y[8]),v*Math.Sin(y[8]),yawRate,
                vl*y[0]+vr*y[1],Motor.R*(y[0]*y[0]+y[1]*y[1]),
                Motor.B*(y[2]*y[2]+y[3]*y[3]),cl*y[2]*y[2]+cr*y[3]*y[3]};
        }
        private static double[] Offset(double[] y,double[] k,double h)
        { var v=new double[13]; for(int i=0;i<13;i++) v[i]=y[i]+h*k[i];return v; }
        public void Step(double vl,double vr,double cl,double cr,double h)
        {
            if(h<=0 || cl<0 || cr<0) throw new ArgumentOutOfRangeException();
            var k1=Rate(s,vl,vr,cl,cr); var k2=Rate(Offset(s,k1,h/2),vl,vr,cl,cr);
            var k3=Rate(Offset(s,k2,h/2),vl,vr,cl,cr); var k4=Rate(Offset(s,k3,h),vl,vr,cl,cr);
            for(int i=0;i<13;i++) s[i]+=h*(k1[i]+2*k2[i]+2*k3[i]+k4[i])/6;
        }
    }

    // Direction and PWM are real input signals; no requested speed is accepted.
    public class SignedBridge
    {
        public readonly PwmWindow Pwm=new PwmWindow();
        public bool Forward { get; private set; }
        public int UnsafeSwitches { get; private set; }
        public int Switches { get; private set; }
        public double BlankUntil { get; private set; }
        public void Direction(double time,bool forward)
        {
            if(forward==Forward)return;
            if(Pwm.Duty(time)>1e-6)UnsafeSwitches++;
            Forward=forward; BlankUntil=time+.002;Switches++;
        }
        public double Voltage(double time) => time<BlankUntil ? 0 : (Forward?12:-12)*Pwm.Duty(time);
    }
}
