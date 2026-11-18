using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public sealed class PwmBenchProbe : IGPIOReceiver
    {
        public PwmBenchProbe(IMachine machine)
        {
            this.machine = machine;
        }

        public void OnGPIO(int number, bool value)
        {
            if(levels[number] == value)
            {
                return;
            }
            levels[number] = value;
            edges.Add($"{machine.ClockSource.CurrentValue.Ticks},{number},{(value ? 1 : 0)}");
        }

        public void Reset()
        {
            System.Array.Clear(levels, 0, levels.Length);
            edges.Clear();
        }

        public void Save(string path)
        {
            using(var writer = new StreamWriter(path))
            {
                writer.WriteLine("virtual_ns,signal,level");
                foreach(var edge in edges)
                {
                    writer.WriteLine(edge);
                }
            }
        }

        // Read-only snapshots taken while the emulation is paused. Avoid capture
        // registers whose read can acknowledge an interrupt on hardware.
        public void Capture(string path, string label, string addresses)
        {
            var fields = new List<string> { label, machine.ClockSource.CurrentValue.Ticks.ToString(CultureInfo.InvariantCulture) };
            foreach(var address in addresses.Split(','))
            {
                fields.Add(machine.SystemBus.ReadDoubleWord(uint.Parse(address, NumberStyles.HexNumber)).ToString("X8"));
            }
            File.AppendAllText(path, string.Join(",", fields) + System.Environment.NewLine);
        }

        private readonly IMachine machine;
        private readonly bool[] levels = new bool[13];
        private readonly List<string> edges = new List<string>();
    }
}
