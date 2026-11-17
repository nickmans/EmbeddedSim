typedef unsigned int u32;
typedef unsigned short u16;
typedef int i32;
#define R(a) (*(volatile u32 *)(a))
#define T2 0x40000000u
#define T3 0x40000400u
#define T4 0x40000800u
#define RCC 0x40023800u
#ifndef MODE
#define MODE 0
#endif
#if MODE == 3
#define COUNTER_START 2
#else
#define COUNTER_START 65530
#endif
struct Telemetry { u32 magic,tick; float reference,estimate,duty; i32 total; u32 counter,saturated; float integral; u32 irq_errors,sequence; };
static volatile struct Telemetry *const log=(volatile struct Telemetry *)0x20000000;
static u16 previous;
static i32 total, history[10];
static u32 ticks;
static float integral;
void reset(void);
void fault(void) { log->magic=0xBADFA017; for(;;) {} }
void tim4(void) {
 log->sequence++;
 if (!(R(T4+0x10)&1)) log->irq_errors++;
 R(T4+0x10)=~1u;
 ticks++;
 u16 count=(u16)R(T3+0x24);
 i32 delta=(u16)(count-previous);
 if (delta>=32768) delta-=65536;
 previous=count; total+=delta;
 u32 slot=(ticks-1)%10;
 float estimate=(float)(total-history[slot])*(6.28318530718f/(1024.0f*0.010f));
 history[slot]=total;
 float reference=0, duty=0;
 if (MODE==0 || MODE==2) {
  if (MODE==2) reference=ticks<100 ? 0 : (ticks<800 ? 200.0f : 60.0f);
  else reference=ticks<100 ? 0 : (ticks<900 ? 60.0f : (ticks<3200 ? 100.0f : 0));
  if (reference==0) integral=0; /* explicit zero drive and controller reset */
  else {
   float error=reference-estimate;
   float candidate=integral+0.05f*0.001f*error;
   float unsaturated=0.006f*error+candidate;
   /* Conditional integration permits unwinding but prevents windup. */
   if (!((unsaturated>1 && error>0)||(unsaturated<0 && error<0))) integral=candidate;
   duty=0.006f*error+integral;
   if (duty<0) duty=0;
   if (duty>1) duty=1;
  }
 } else if (MODE==1) {
  duty=ticks<100 ? 0 : (ticks<800 ? .5f : (ticks<1000 ? 1.0f : 0));
 }
 u32 compare=(u32)(duty*1000.0f+0.5f);
 if (compare>1000) compare=1000;
 R(T2+0x34)=compare;
 log->tick=ticks; log->reference=reference; log->estimate=estimate;
 log->duty=(float)compare/1000.0f; log->total=total; log->counter=count;
 log->saturated=(compare==0 || compare==1000); log->integral=integral;
 log->sequence++;
}
__attribute__((section(".vectors"),used))
void (*const vectors[47])(void)={ [0]=(void (*)(void))0x20020000,[1]=reset,
 [2]=fault,[3]=fault,[4]=fault,[5]=fault,[6]=fault,[46]=tim4 };
extern u32 _sbss,_ebss,_sdata,_edata,_sidata;
void reset(void) {
 for (u32 *p=&_sbss;p<&_ebss;p++) *p=0;
 u32 *src=&_sidata;
 for(u32 *p=&_sdata;p<&_edata;p++) *p=*src++;
 for (u32 i=0;i<11;i++) ((volatile u32 *)log)[i]=0;
 R(0xE000ED08)=0x08000000;
 R(RCC)|=1; while (!(R(RCC)&2)) {}
 R(RCC+8)=4u<<13; /* HSI16, AHB/1 APB1/1 APB2/2 */
 while ((R(RCC+8)&12)!=0) {}
 R(RCC+0x30)|=1; R(RCC+0x40)|=7; (void)R(RCC+0x40);
 R(0x40020000)=(R(0x40020000)&~0xF003u)|0xA002u;
 R(0x40020020)=(R(0x40020020)&~0xFF00000Fu)|0x22000001u;
 R(T2)=128; R(T2+0x28)=15; R(T2+0x2C)=999;
 R(T2+0x18)=0x68; R(T2+0x34)=0; R(T2+0x20)=1;
 R(T2+0x14)=1; R(T2+0x10)=0; R(T2)=129;
 R(T3+0x2C)=65535; R(T3+0x24)=COUNTER_START; previous=COUNTER_START;
 R(T3+0x18)=0x101; R(T3+0x20)=0x11; R(T3+8)=3; R(T3)=1;
 R(T4+0x28)=15; R(T4+0x2C)=999; R(T4+0x14)=1; R(T4+0x10)=0;
 R(T4+0x0C)=1; R(0xE000E100)=1u<<30; R(T4)=1;
 log->magic=0xC0DEF407;
 for (;;) __asm__ volatile("wfi");
}
