/* Real register-level F407 diagnostic. The host writes only this RAM mailbox.
 * Every peripheral configuration/write below is executed by Cortex-M4 code. */
typedef unsigned int u32;
#define R(a) (*(volatile u32 *)(a))
#define RCC 0x40023800u
#define GPIOA 0x40020000u
#define T2 0x40000000u
#define T3 0x40000400u
#define T4 0x40000800u
/* 0 magic, 1 request, 2 ack, 3 opcode, 4..9 args,
 * 10 encoder count, 11 ISR count, 12 bad ISR flags, 13 SR after clear. */
static volatile u32 *const m=(volatile u32 *)0x20000000;
void reset(void);
void fault(void) { m[0]=0xBADFA017; for (;;) {} }
void tim4(void) {
 u32 sr=R(T4+0x10);
 if (!(sr&1)) m[12]++;
 R(T4+0x10)=~1u; /* UIF is rc_w0; preserve unrelated flags. */
 m[13]=R(T4+0x10)&1;
 m[11]++;
}
__attribute__((section(".vectors"),used))
void (*const vectors[47])(void)={
 [0]=(void (*)(void))0x20020000,[1]=reset,
 [2]=fault,[3]=fault,[4]=fault,[5]=fault,[6]=fault,[46]=tim4
};
static void pin(u32 p,u32 mode,u32 af) {
 u32 shift=2*p, ashift=4*(p%8), ar=GPIOA+0x20+4*(p/8);
 R(GPIOA)=(R(GPIOA)&~(3u<<shift))|(mode<<shift);
 R(ar)=(R(ar)&~(15u<<ashift))|(af<<ashift);
}
static void clock(u32 source,u32 hpre,u32 ppre) {
 R(RCC)|=1;
 while (!(R(RCC)&2)) {}
 R(RCC+8)&=~3u;
 while ((R(RCC+8)&12)!=0) {}
 R(RCC)&=~(1u<<24);
 while (R(RCC)&(1u<<25)) {}
 if (source) {
  R(RCC)|=1u<<16;
  while (!(R(RCC)&(1u<<17))) {}
 }
 if (source==2) {
  R(0x40007000)|=1u<<14; /* voltage scale 1 (reset value already scale 1) */
  R(0x40023C00)=0x705; /* caches/prefetch and five flash wait states */
  /* Preserve reserved bits at reset values, as the vendor HAL does. */
  R(RCC+4)=(R(RCC+4)&~(63u|(511u<<6)|(3u<<16)|(1u<<22)|(15u<<24)))
           |8u|(336u<<6)|(1u<<22)|(7u<<24); /* HSE8 /8 *336 /2 */
  R(RCC)|=1u<<24;
  while (!(R(RCC)&(1u<<25))) {}
 }
 R(RCC+8)=(hpre<<4)|(ppre<<10)|(4u<<13)|source;
 while (((R(RCC+8)>>2)&3)!=source) {}
}
void reset(void) {
 for (u32 i=0;i<16;i++) m[i]=0;
 R(0xE000ED08)=0x08000000;
 R(RCC+0x30)|=1; R(RCC+0x40)|=7|(1u<<28);
 (void)R(RCC+0x40); /* clock enable write/readback before peripheral accesses */
 pin(0,2,1); pin(6,2,2); pin(7,2,2);
 m[0]=0xC0DEF407;
 for (;;) {
  m[10]=R(T3+0x24); m[14]=R(T2+0x24);
  if (m[1]==m[2]) continue;
  u32 a=m[4],b=m[5],c=m[6],d=m[7];
  switch(m[3]) {
  case 1: /* stopped PWM setup; preload flags: bit0 ARPE, bit1 OC1PE */
   R(T2)=0; R(T2+0x20)=0; R(T2+0x18)=0;
   R(T2)=((d&1)?128:0);
   R(T2+0x28)=a; R(T2+0x2C)=b;
   R(T2+0x18)=0x60|((d&2)?8:0); R(T2+0x34)=c;
   R(T2+0x20)=1; R(T2+0x14)=1; R(T2+0x10)=0;
   R(T2)|=1; break;
  case 2: /* encoder setup, initial count */
   R(T3)=0; R(T3+0x20)=0; R(T3+8)=0;
   R(T3+0x2C)=b; R(T3+0x24)=a;
   R(T3+0x18)=0x101; R(T3+0x20)=0x11;
   R(T3+8)=3; R(T3)=1; break;
  case 3: R(T3)=a; break;
  case 4: clock(a,b,c); break;
  case 5: pin(a,b,c); break;
  case 6: /* periodic ISR setup */
   R(T4)=0; R(T4+0x0C)=0;
   R(T4+0x28)=a; R(T4+0x2C)=b; R(T4+0x14)=1;
   R(T4+0x10)=0; m[11]=m[12]=m[13]=0;
   R(T4+0x0C)=1; R(0xE000E100)=1u<<30; R(T4)=1; break;
  case 7: R(T2+a)=b; break; /* offset,value; used for real preload writes */
  case 8: R(RCC+0x40)=(R(RCC+0x40)&~a)|b; break;
  case 9: R(RCC+0x20)|=a; R(RCC+0x20)&=~a; break;
  case 10: R(T4)=a; break;
  case 11:
   R(T4)=0; R(T4+0x0C)=0; R(T4+0x10)=0;
   R(T4+0x14)=1; m[15]=R(T4+0x10)&1; break;
  default: m[0]=0xBAD0C0DE;
  }
  m[2]=m[1];
 }
}
