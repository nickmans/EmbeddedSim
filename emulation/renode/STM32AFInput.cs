// Generic STM32 alternate-function input route. Pin/AF/timer wiring is platform data.
using Antmicro.Renode.Core;
namespace Antmicro.Renode.Peripherals.GPIOPort
{
    public class STM32AFInput : IGPIOReceiver, IGPIOSender
    {
        public STM32AFInput(STM32_GPIOPort port, int pin, int alternateFunction)
        {
            this.port=port; this.pin=pin; this.alternateFunction=alternateFunction;
        }
        public void OnGPIO(int number, bool value)
        {
            // GPIO IDR/EXTI still see the physical signal through the parent port.
            // Only this AF-specific peripheral route is disconnected by the mux.
            var mode=(port.ReadDoubleWord(0)>>(2*pin))&3;
            var af=(port.ReadDoubleWord(0x20+4*(pin/8))>>(4*(pin%8)))&15;
            if(mode==2 && af==alternateFunction) IRQ.Set(value);
        }
        public void Reset() { IRQ.Unset(); }
        public GPIO IRQ { get; } = new GPIO();
        private readonly STM32_GPIOPort port;
        private readonly int pin;
        private readonly int alternateFunction;
    }
}
