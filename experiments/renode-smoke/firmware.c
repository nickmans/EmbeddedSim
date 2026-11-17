/* Diagnostic firmware, not a motor controller. No vendor library required. */
typedef unsigned int u32;
#define R(a) (*(volatile u32 *)(a))
#define T2 0x40000000u
#define T3 0x40000400u
#define T4 0x40000800u
volatile u32 *const result = (volatile u32 *)0x20000000;
void reset(void);
void fault(void) { for (;;) {} }
void tim4(void) { R(T4+0x10)=0; result[1]++; }
__attribute__((section(".vectors"),used))
void (*const vectors[16+31])(void) = {
 [0]=(void (*)(void))0x20020000, [1]=reset,
 [2]=fault, [3]=fault, [4]=fault, [5]=fault, [6]=fault,
 [16+30]=tim4
};
void reset(void) {
 result[0]=0; result[1]=0; result[2]=0;
 R(0xE000ED08)=0x08000000; /* VTOR */
 R(0x40023830)|=1; /* RCC GPIOAEN */
 R(0x40023840)|=7; /* TIM2/3/4EN */
 /* PA0 AF1 TIM2_CH1; PA6/7 AF2 TIM3_CH1/2. */
 R(0x40020000)=(R(0x40020000)&~0xF003u)|0xA002u;
 R(0x40020020)=(R(0x40020020)&~0xFF00000Fu)|0x22000001u;
 R(T2+0x28)=15; R(T2+0x2C)=999; R(T2+0x34)=250;
 R(T2+0x18)=6u<<4; R(T2+0x20)=1; R(T2+0x14)=1; R(T2)=1;
 R(T3+0x2C)=65535; R(T3+0x18)=0x101; R(T3+0x20)=0x11;
 R(T3+0x08)=3; R(T3)=1; /* encoder mode 3 */
 R(T4+0x28)=15; R(T4+0x2C)=999; R(T4+0x14)=1;
 R(T4+0x10)=0; R(T4+0x0C)=1;
 R(0xE000E100)=1u<<30; R(T4)=1;
 result[0]=0xC0DEF407;
 for (;;) { result[2]=R(T3+0x24); }
}
