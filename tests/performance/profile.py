"""Instrument a scratch copy of RobotLoop for coarse wall-clock attribution."""
import argparse
import json
import sys
from pathlib import Path
from threading import Event

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--checkout", type=Path, default=Path(__file__).resolve().parents[2])
parser.add_argument("--elf", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.checkout.resolve() / "setup"))
import live
from config import default_config

original = live.machine_commands
labels = ("model", "encoder_gpio", "driver_load", "observer", "format_csv", "write_csv")


def instrument(scratch, *args, **kwargs):
    commands = original(scratch, *args, **kwargs)
    source = scratch / "RobotLoop.cs"
    code = source.read_text()
    replacements = [
        ("private void Tick()", """private long modelTicks, encoderTicks, driverTicks, observeTicks, formatTicks, writeTicks;
        private static long Stamp() => System.Diagnostics.Stopwatch.GetTimestamp();
        private void Tick()"""),
        ("model.Step(voltage", "var stamp=Stamp(); model.Step(voltage"),
        ("for(int wheel=0;wheel<2;wheel++)", "modelTicks+=Stamp()-stamp; stamp=Stamp();\n            for(int wheel=0;wheel<2;wheel++)"),
        ("time=now;\n            leftDrag", "encoderTicks+=Stamp()-stamp; stamp=Stamp();\n            time=now;\n            leftDrag"),
        ("if(machine.ClockSource.CurrentValue.Ticks>=nextSample)",
         "driverTicks+=Stamp()-stamp;\n            if(machine.ClockSource.CurrentValue.Ticks>=nextSample)"),
        ("observer?.Read();", "var stamp=Stamp(); observer?.Read(); observeTicks+=Stamp()-stamp; stamp=Stamp();"),
        ('rows.Add(string.Join(",",fields));', 'rows.Add(string.Join(",",fields)); formatTicks+=Stamp()-stamp;'),
        ("using(var output=new StreamWriter(path))", "var stamp=Stamp();\n            using(var output=new StreamWriter(path))"),
    ]
    for old, new in replacements:
        if old not in code:
            raise RuntimeError(f"Profiling hook missing: {old}")
        code = code.replace(old, new, 1)
    start = code.index("public void ExportLive")
    end = code.index("        }\n\n        public void Finish", start)
    code = code[:end] + '''            writeTicks+=Stamp()-stamp;
            File.WriteAllText(path+".profile", string.Join(",",new long[] {
                System.Diagnostics.Stopwatch.Frequency, modelTicks, encoderTicks, driverTicks,
                observeTicks, formatTicks, writeTicks}));
''' + code[end:]
    source.write_text(code)
    return commands


live.machine_commands = instrument
config = default_config()
config["scenario"].update(observer="example-v1", duration_s=3)
machine = live.LiveMachine(args.elf.read_bytes(), config, args.output.resolve(), Event())
try:
    while machine.virtual_ns < machine.limit:
        machine.step(machine.limit)
    freq, *counts = map(int, (machine.scratch / "slice.csv.profile").read_text().split(","))
    phases = dict(zip(labels, (count / freq for count in counts)))
    print(json.dumps({"advancing_wall_s": machine.active_seconds, "virtual_s": 3, "phases_s": phases}))
finally:
    machine.close()
