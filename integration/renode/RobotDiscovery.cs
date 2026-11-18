using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    // Discovery observes the qualified physical routes independently of robot wiring.
    public class RobotDiscovery : IGPIOReceiver
    {
        public RobotDiscovery(IMachine machine)
        {
            this.machine=machine;
            bus=machine.SystemBus;
            Reset();
        }

        public void Reset()
        {
            pins=new[] {new Signal(),new Signal(),new Signal(),new Signal()};
        }

        public void OnGPIO(int number, bool value)
        {
            var signal=pins[number];
            if(signal.High==value) return;
            var now=machine.ClockSource.CurrentValue.TotalSeconds;
            signal.High=value;
            signal.Edges++;
            signal.LastEdge=now;
            if(value)
            {
                if(signal.Rise.HasValue && signal.Fall>signal.Rise && now>signal.Rise.Value)
                {
                    signal.Period=now-signal.Rise.Value;
                    signal.Duty=(signal.Fall.Value-signal.Rise.Value)/signal.Period;
                }
                signal.Rise=now;
            }
            else signal.Fall=now;
        }

        public void Capture(string path)
        {
            var now=machine.ClockSource.CurrentValue.TotalSeconds;
            var fields=new List<string> {Format(now)};
            foreach(var address in new uint[] {
                0x40023808,0x40023830,0x40023840,
                0x40020000,0x40020004,0x40020020,0x40020400,0x40020404,0x40020420})
                fields.Add(bus.ReadDoubleWord(address).ToString(CultureInfo.InvariantCulture));
            foreach(var address in new uint[] {0x40000000,0x40000400,0x40000800})
                foreach(var offset in new uint[] {0,8,0x18,0x20,0x28,0x2c,0x34,0x38})
                    fields.Add(bus.ReadDoubleWord(address+offset).ToString(CultureInfo.InvariantCulture));
            foreach(var signal in pins)
            {
                var fresh=signal.Period>0 && now-signal.LastEdge<=2*signal.Period;
                fields.AddRange(new[] {signal.High?"1":"0",signal.Edges.ToString(),
                    Format(now-signal.LastEdge),fresh?Format(signal.Period):"",fresh?Format(signal.Duty):""});
            }
            File.AppendAllText(path,string.Join("\t",fields)+Environment.NewLine);
        }

        private class Signal
        {
            public bool High;
            public int Edges;
            public double LastEdge,Period,Duty;
            public double? Rise,Fall;
        }
        private static string Format(double value) => value.ToString("R",CultureInfo.InvariantCulture);
        private readonly IMachine machine;
        private readonly IBusController bus;
        private Signal[] pins;
    }
}
