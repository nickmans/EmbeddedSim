ENTRY(reset)
MEMORY {
 FLASH(rx) : ORIGIN = 0x08000000, LENGTH = 1M
 RAM(rwx) : ORIGIN = 0x20001000, LENGTH = 124K
}
SECTIONS {
 .vectors : { KEEP(*(.vectors)) } > FLASH
 .text : { *(.text*) *(.rodata*) } > FLASH
 .data : { _sdata = .; *(.data*) _edata = .; } > RAM AT> FLASH
 _sidata = LOADADDR(.data);
 .bss (NOLOAD) : { . = ALIGN(4); _sbss = .; *(.bss*) *(COMMON) . = ALIGN(4); _ebss = .; } > RAM
 /DISCARD/ : { *(.comment) *(.ARM.attributes) }
}
