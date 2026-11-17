using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    // External observer only; never writes MCU registers or substitutes firmware.
    public class EdgeProbe : IGPIOReceiver
    {
        public EdgeProbe(IMachine machine) { this.machine = machine; }
        public void OnGPIO(int number, bool value)
        {
            if(value == state) return;
            var now = machine.ClockSource.CurrentValue.TotalSeconds;
            events.Add(now.ToString("R", System.Globalization.CultureInfo.InvariantCulture)+":"+(value?"1":"0"));
            if(value) { Period = now - lastRise; lastRise = now; Rising++; }
            else { HighTime = now - lastRise; Falling++; }
            state = value;
        }
        public void Reset() { events.Clear(); Rising = Falling = 0; lastRise = Period = HighTime = 0; state = false; }
        public int Rising { get; private set; }
        public int Falling { get; private set; }
        public double Period { get; private set; }
        public double HighTime { get; private set; }
        public string Trace => string.Join(",", events);
        private readonly System.Collections.Generic.List<string> events=new System.Collections.Generic.List<string>();
        private readonly IMachine machine;
        private double lastRise;
        private bool state;
    }
}
