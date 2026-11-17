ENTRY(reset)
MEMORY { FLASH(rx) : ORIGIN = 0x08000000, LENGTH = 1M }
SECTIONS {
 .vectors : { KEEP(*(.vectors)) } > FLASH
 .text : { *(.text*) *(.rodata*) } > FLASH
 /DISCARD/ : { *(.comment) *(.ARM.attributes) }
}
