#include "hardware.h"
static volatile u32 *const m=(volatile u32 *)0x20000000;
void reset(void);
void fault(void) { m[0]=0xBADFA017; for(;;) {} }
void tick(void) { if(!(R(T2+0x10)&1)) m[11]++; R(T2+0x10)=~1u; m[10]++; }
__attribute__((section(".vectors"),used))
void (*const vectors[45])(void)={ [0]=(void (*)(void))0x20020000,[1]=reset,
 [2]=fault,[3]=fault,[4]=fault,[5]=fault,[6]=fault,[44]=tick };
void reset(void) {
 runtime_init(); for(u32 k=0;k<16;k++) m[k]=0;
 hw_init(65534,2); R(T2+0x34)=250; R(T2+0x38)=750;
 m[0]=0xC0DEF407;
 for(;;) {
  m[8]=R(T3+0x24); m[9]=R(T4+0x24);
  if(m[1]==m[2]) continue;
  u32 a=m[4], b=m[5];
  switch(m[3]) {
   case 1:R(T2+0x34)=a;R(T2+0x38)=b;break;
   case 2:R(T3)=a&1;R(T4)=(a>>1)&1;break;
   case 3:R(T3+0x24)=a;R(T4+0x24)=b;break;
   case 4:pin(GB,6,a,b);pin(GB,7,a,b);break;
   case 5:pin(GA,1,2,a);break;
   case 6:R(GA+0x18)=((a&1)?1u<<4:1u<<20)|((a&2)?1u<<5:1u<<21);break;
   case 7:R(RCC+0x40)=(R(RCC+0x40)&~4u)|(a?4u:0);break;
  }
  m[2]=m[1];
 }
}
