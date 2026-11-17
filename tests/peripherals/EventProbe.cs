using System.Collections.Generic;
using System.Globalization;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class EventProbe : IGPIOReceiver
    {
        public EventProbe(IMachine machine) { this.machine=machine; }
        public void OnGPIO(int number, bool value)
        {
            if(value==State) return;
            State=value;
            events.Add(machine.ClockSource.CurrentValue.TotalSeconds.ToString("R", CultureInfo.InvariantCulture)+":"+(value?"1":"0"));
        }
        public void Clear() { events.Clear(); }
        public void Reset() { events.Clear(); State=false; }
        public bool State { get; private set; }
        public string Trace => string.Join(",", events);
        private readonly IMachine machine;
        private readonly List<string> events=new List<string>();
    }
}
