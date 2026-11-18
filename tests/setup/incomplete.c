// Models firmware waiting for a device canary before any pin initialization.
#include "../../firmware/robot/hardware.h"

void reset(void);
__attribute__((section(".vectors"), used))
void (*const vectors[])(void) = {
    [0] = (void (*)(void))0x20020000, [1] = reset
};

void reset(void)
{
    runtime_init();
    for (;;) __asm__ volatile("wfi");
}
