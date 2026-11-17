typedef unsigned int u32;
typedef unsigned short u16;
typedef int i32;
#define R(a) (*(volatile u32 *)(a))
#define RCC 0x40023800u
#define GA 0x40020000u
#define GB 0x40020400u
#define T2 0x40000000u
#define T3 0x40000400u
#define T4 0x40000800u
extern u32 _sbss,_ebss,_sdata,_edata,_sidata;
static void runtime_init(void) {
 for(u32 *p=&_sbss;p<&_ebss;p++) *p=0;
 u32 *s=&_sidata; for(u32 *p=&_sdata;p<&_edata;p++) *p=*s++;
}
static void pin(u32 port,u32 p,u32 mode,u32 af) {
 R(port)=(R(port)&~(3u<<(2*p)))|(mode<<(2*p));
 u32 ar=port+0x20+4*(p/8), sh=4*(p%8);
 R(ar)=(R(ar)&~(15u<<sh))|(af<<sh);
}
static void hw_init(u16 left,u16 right) {
 R(0xE000ED08)=0x08000000;
 R(RCC)|=1; while(!(R(RCC)&2)) {}
 R(RCC+8)=4u<<13; while((R(RCC+8)&12)!=0) {}
 R(RCC+0x30)|=3; R(RCC+0x40)|=7; (void)R(RCC+0x40);
 pin(GA,0,2,1); pin(GA,1,2,1); pin(GA,6,2,2); pin(GA,7,2,2);
 pin(GB,6,2,2); pin(GB,7,2,2); pin(GA,4,1,0); pin(GA,5,1,0);
 R(GA+0x18)=(1u<<4)|(1u<<5);
 R(T2)=128; R(T2+0x28)=15; R(T2+0x2C)=999;
 R(T2+0x18)=0x6868; R(T2+0x34)=0; R(T2+0x38)=0;
 R(T2+0x20)=0x11; R(T2+0x14)=1; R(T2+0x10)=0;
 for(u32 side=0;side<2;side++) {
  u32 base=side?T4:T3;
  R(base+0x2C)=65535; R(base+0x24)=side?right:left;
  R(base+0x18)=0x101; R(base+0x20)=0x11; R(base+8)=3; R(base)=1;
 }
 R(T2+0x0C)=1; R(0xE000E100)=1u<<28; R(T2)=129;
}
