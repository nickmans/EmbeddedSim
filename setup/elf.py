"""Validate the ELF subset loaded into the qualified Cortex-M platform."""
import struct

from config import SetupError

MAX_ELF_BYTES = 16 * 1024 * 1024
FLASH = (0x08000000, 0x08100000)
RAM = ((0x20000000, 0x20020000), (0x10000000, 0x10010000))
MEMORY = (FLASH, *RAM)


def inside(start, size, regions=MEMORY):
    return any(low <= start < high and start + size <= high for low, high in regions)


def validate_elf(image):
    if not 52 <= len(image) <= MAX_ELF_BYTES or image[:7] != b"\x7fELF\x01\x01\x01":
        raise SetupError("Select a little-endian ELF32 executable (up to 16 MiB).")
    kind, machine, version, entry, phoff, _, flags, size, phsize, count, *_ = struct.unpack_from(
        "<HHIIIIIHHHHHH", image, 16)
    if (kind, machine, version, flags >> 24) != (2, 40, 1, 5):
        raise SetupError("ELF must be a statically linked ARM EABI5 executable.")
    if size != 52 or phsize != 32 or not 1 <= count <= 128 or phoff < size or phoff + count * phsize > len(image):
        raise SetupError("Invalid ELF program-header table.")

    segments = []
    virtual_ranges = []
    load_ranges = []
    executable = []
    vectors = None
    for i in range(count):
        ptype, offset, vaddr, paddr, filesz, memsz, permissions, align = struct.unpack_from(
            "<8I", image, phoff + i * phsize)
        if ptype in (2, 3):
            raise SetupError("Dynamic linking and load interpreters are unsupported.")
        if ptype != 1:
            continue
        if (filesz > memsz or offset + filesz > len(image) or
                (align > 1 and (align & (align - 1) or (vaddr - offset) % align))):
            raise SetupError(f"LOAD segment {i} has invalid size, offset, or alignment.")
        if memsz == 0:
            continue
        if not inside(vaddr, memsz):
            raise SetupError(f"LOAD segment {i} runtime range is outside Flash, SRAM, and CCM.")
        if any(vaddr < hi and lo < vaddr + memsz for lo, hi in virtual_ranges):
            raise SetupError("ELF runtime LOAD ranges overlap.")
        virtual_ranges.append((vaddr, vaddr + memsz))
        if filesz == 0:
            continue
        if not inside(paddr, filesz):
            raise SetupError(f"LOAD segment {i} load address is outside Flash, SRAM, and CCM.")
        if paddr != vaddr and not (inside(paddr, filesz, (FLASH,)) and inside(vaddr, memsz, RAM)):
            raise SetupError("Different load and runtime addresses require Flash-backed SRAM/CCM initialization.")
        if any(paddr < hi and lo < paddr + filesz for lo, hi in load_ranges):
            raise SetupError("ELF file-backed LOAD ranges overlap.")
        load_ranges.append((paddr, paddr + filesz))
        data = image[offset:offset + filesz]
        segments.append((paddr, data))
        if paddr == vaddr == FLASH[0] and filesz >= 8:
            vectors = struct.unpack_from("<2I", data)
        if permissions & 1 and paddr == vaddr and inside(vaddr, filesz, (FLASH,)):
            executable.append((vaddr, vaddr + filesz))

    if vectors is None:
        raise SetupError("A file-backed vector table must start at Flash address 0x08000000.")
    sp, reset = vectors
    if sp % 8 or not any(low < sp <= high for low, high in RAM):
        raise SetupError("The initial stack pointer must be 8-byte aligned within SRAM or CCM.")
    for name, address in (("Reset vector", reset), ("ELF entry", entry)):
        if not address & 1 or not any(low <= address - 1 and address + 1 <= high for low, high in executable):
            raise SetupError(f"{name} must point to Thumb code in a file-backed executable Flash segment.")
    return segments
