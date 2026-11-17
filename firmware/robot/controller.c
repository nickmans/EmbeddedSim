#include "hardware.h"
#include <math.h>
#ifndef MODE
#define MODE 0
#endif
struct Telemetry {
 u32 magic,tick; float reference[2],estimate[2],signed_duty[2];
 i32 total[2]; u32 counter[2]; float x,y,yaw;
 u32 direction,sequence,irq_errors; float integral[2]; u32 blank[2];
};
static volatile struct Telemetry *const out=(volatile struct Telemetry *)0x20000000;
static struct Telemetry frame;
static u32 published;
static u16 previous[2]; static i32 total[2],history[2][20];
static float integral[2],x,y,yaw;
static u32 ticks,forward[2],pending[2],blank[2];
void reset(void);
void fault(void) { out->magic=0xBADFA017; for(;;){} }
static float magnitude(float x) { return x<0?-x:x; }
static void reference(float *l,float *r) {
 *l=*r=0;
 if(ticks>=200 && ticks<2000) *l=*r=10;
 else if(ticks>=2800 && ticks<4400) { *l=-5;*r=5; }
 else if(ticks>=5200 && ticks<7000) { *l=6;*r=10; }
 else if(ticks>=7800 && ticks<9600) *l=*r=-8;
}
static float drive(u32 side,float effort) {
 u32 compare=0, sign=effort>=0;
 if(blank[side]) {
  blank[side]--;
  if(blank[side]==3) {
   forward[side]=pending[side];
   R(GA+0x18)=1u<<((forward[side]?0:16)+4+side);
  }
 }
 if(!blank[side] && magnitude(effort)>=.002f) {
  if(sign!=forward[side]) { pending[side]=sign;blank[side]=6; }
  else { compare=(u32)(1000*magnitude(effort)+.5f); if(compare>1000)compare=1000; }
 }
 R(T2+0x34+4*side)=compare;
 return (forward[side]?1.0f:-1.0f)*(float)compare/1000;
}
void tick(void) {
 struct Telemetry *out=&frame;
 out->sequence++;
 if(!(R(T2+0x10)&1))out->irq_errors++;
 R(T2+0x10)=~1u; ticks++;
 float refs[2];reference(&refs[0],&refs[1]);
 float distance[2];
 for(u32 side=0;side<2;side++) {
  u16 count=(u16)R((side?T4:T3)+0x24);
  i32 delta=(u16)(count-previous[side]); if(delta>=32768)delta-=65536;
  previous[side]=count;total[side]+=delta;
  distance[side]=(float)delta*(.05f*6.28318530718f/4096);
  u32 slot=(ticks-1)%20;
  float speed=(float)(total[side]-history[side][slot])*(6.28318530718f/(4096*.020f));
  history[side][slot]=total[side];
  float error=refs[side]-speed;
  float candidate=integral[side]+.02f*.001f*error;
  float unsat=.04f*error+candidate;
  if(!blank[side] && !((unsat>1 && error>0)||(unsat< -1 && error<0)))integral[side]=candidate;
  float effort=.04f*error+integral[side];
  if(refs[side]==0 && magnitude(speed)<.10f) { integral[side]=0;effort=0; }
  if(effort>1)effort=1;if(effort< -1)effort=-1;
  out->reference[side]=refs[side];out->estimate[side]=speed;
  out->signed_duty[side]=drive(side,effort);
  out->total[side]=total[side];out->counter[side]=count;
  out->integral[side]=integral[side];out->blank[side]=blank[side];
 }
 float ds=(distance[0]+distance[1])/2, da=(distance[1]-distance[0])/.30f;
 float mid=yaw+da/2;
 x+=ds*cosf(mid);y+=ds*sinf(mid);yaw+=da;
 while(yaw>=3.14159265359f)yaw-=6.28318530718f;
 while(yaw< -3.14159265359f)yaw+=6.28318530718f;
 out->x=x;out->y=y;out->yaw=yaw;out->tick=ticks;
 out->direction=forward[0]|(forward[1]<<1);
 out->sequence++;
 /* Copy to the inactive RAM bank, then publish with one atomic word store.
  * Logging can always read a complete frame, even during this ISR. */
 u32 next=published^1u;
 for(u32 k=0;k<22;k++) R(0x20000000+128*next+4*k)=((u32 *)&frame)[k];
 published=next;R(0x20000100)=next;
}
__attribute__((section(".vectors"),used))
void (*const vectors[45])(void)={ [0]=(void (*)(void))0x20020000,[1]=reset,
 [2]=fault,[3]=fault,[4]=fault,[5]=fault,[6]=fault,[44]=tick };
void reset(void) {
 runtime_init();for(u32 i=0;i<22;i++)((volatile u32 *)out)[i]=0;
 R(0x20000100)=0;frame.magic=0xC0DEF407;
 forward[0]=forward[1]=1;previous[0]=65530;previous[1]=2;
 hw_init(previous[0],previous[1]);out->magic=0xC0DEF407;
 for(;;)__asm__ volatile("wfi");
}
