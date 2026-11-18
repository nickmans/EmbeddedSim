// Bare-metal fixture with no firmware observation ABI.
#include "../../firmware/robot/hardware.h"

static volatile u32 pwm_compare = 250;

void reset(void);
void fault(void) { for (;;) {} }
void tick(void) { R(T2 + 0x10) = ~1u; }

__attribute__((section(".vectors"), used))
void (*const vectors[45])(void) = {
    [0] = (void (*)(void))0x20020000, [1] = reset,
    [2] = fault, [3] = fault, [4] = fault, [5] = fault, [6] = fault, [44] = tick
};

void reset(void)
{
    runtime_init();
    // This RAM word is deliberately ordinary scratch for external firmware.
    R(0x20000100) = 0x12345678;
    hw_init(0, 0);
    R(T2 + 0x34) = pwm_compare;
    R(T2 + 0x38) = 1000;
    for (;;) __asm__ volatile("wfi");
}
