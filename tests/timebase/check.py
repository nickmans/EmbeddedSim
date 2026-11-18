"""Measure HAL delay markers with Renode virtual timestamps."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "setup"))

from runner import ERRORS, GCC, PLATFORM, RENODE

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--legacy", action="store_true", help="Capture stock fixed-clock behavior and fail the same timing assertions")
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True)
elf = out / "hal-clock.elf"
subprocess.run(["bash", str(ROOT / "firmware/cubef4-hal/build.sh"), str(elf),
                str(ROOT / "tests/timebase/hal_clock.c")], cwd=ROOT, check=True)
with TemporaryDirectory(prefix="clock-check-", dir="/tmp") as tmp:
    scratch = Path(tmp)
    subprocess.run([sys.executable, str(PLATFORM / "prepare.py"), str(scratch)], check=True)
    probe = scratch / "PwmBenchProbe.cs"
    shutil.copyfile(ROOT / "integration/renode/PwmBenchProbe.cs", probe)
    platform = (PLATFORM / "stm32f407vg-robot.repl").read_text()
    if args.legacy:
        platform = platform.replace(
            "systickClock: Miscellaneous.STM32F407SysTickClock @ sysbus\n    nvic: nvic\n", ""
        ).replace("    systickClock: systickClock\n", "")
    platform += """
probe: Miscellaneous.PwmBenchProbe @ sysbus
gpioPortA:
    4 -> probe@0
    5 -> probe@1
"""
    (scratch / "clock.repl").write_text(platform)
    symbols = subprocess.check_output([str(Path(GCC).with_name("arm-none-eabi-nm")), "-n", str(elf)], text=True)
    names = ("flags_seen", "tick_deltas", "irq_deltas")
    offsets = {n: int(re.search(rf"(?m)^([0-9a-f]+) \w {n}$", symbols)[1], 16) for n in names}
    addresses = [offsets[n] + i * 4 for n in names for i in range(1 if n == "flags_seen" else 4)]
    sources = [n for n in ("QualifiedSTM32Timer.cs", "QualifiedSTM32RCC.cs", "STM32AFInput.cs", probe.name)
               if (scratch / n).is_file()]
    lines = ["logLevel 2", *(f"include @{scratch / name}" for name in sources), "mach create",
             f"machine LoadPlatformDescription @{scratch}/clock.repl", f"sysbus LoadELF @{scratch / 'clock.elf'}",
             "cpu VectorTableOffset 0x08000000", 'emulation RunFor "0.300"',
             f'sysbus.probe Save "{scratch}/edges.csv"',
             f'sysbus.probe Capture "{scratch}/state.csv" "final" "{",".join(f"{address:x}" for address in addresses)}"',
             "quit"]
    shutil.copyfile(elf, scratch / "clock.elf")
    script = scratch / "check.resc"
    script.write_text("\n".join(lines) + "\n")
    with (out / "renode.log").open("w") as log:
        subprocess.run([str(RENODE), "--disable-gui", "--plain", "--console", str(script)], check=True,
                       env=dict(os.environ, XDG_CONFIG_HOME=str(scratch / "config")), cwd=scratch,
                       stdout=log, stderr=subprocess.STDOUT, timeout=60)
    assert not ERRORS.search((out / "renode.log").read_text()), "Inspect renode.log"
    for name in ("edges.csv", "state.csv"):
        shutil.copyfile(scratch / name, out / name)

with (out / "edges.csv").open() as stream:
    edge_data = [(int(r["virtual_ns"]), int(r["signal"]), int(r["level"])) for r in csv.DictReader(stream)]
markers = [t for t, signal, level in edge_data if signal == 0]
widths = [b - a for a, b in zip(markers[::2], markers[1::2])]
irq_intervals = []
for start, end in list(zip(markers[::2], markers[1::2]))[:4]:
    ticks = [t for t, signal, _ in edge_data if signal == 1 and start < t < end]
    irq_intervals.append([b - a for a, b in zip(ticks, ticks[1:])])
with (out / "state.csv").open() as stream:
    flags, *counts = [int(value, 16) for value in next(csv.reader(stream))[2:]]
result = {"hal_delay_ns": widths[:4], "counter_only_wrap_ns": widths[4] if len(widths) == 5 else None, "irq_intervals_ns": irq_intervals, "hal_tick_deltas": counts[:4],
          "irq_count_deltas": counts[4:], "counter_only_countflag_observed": bool(flags)}
(out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
assert len(widths) == 5 and flags and counts == [11] * 8
assert abs(widths[4] - 1e6) <= 2000, "COUNTFLAG cadence with IRQs disabled"
assert all(9_900_000 <= width <= 11_100_000 for width in widths[:4]), "HAL_Delay is not 10–11 ms in virtual time"
assert all(len(intervals) >= 8 and all(abs(period - 1e6) <= 2000 for period in intervals)
           for intervals in irq_intervals), "SysTick IRQs do not have 1 ms cadence"
