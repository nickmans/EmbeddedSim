"""Run one ELF with and without a stuck right encoder channel and plot the results."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "setup"))

from assertions import read_recording
from config import default_config
from runner import build_example, write_json


def plot(output, records):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(5, 1, figsize=(10, 10.2), sharex=True, layout="constrained")
    for label, data in records.items():
        time = data["time_s"]
        for axis, column in zip(axes, ("wr_rad_s", "estimate_r_rad_s", "ir_A", "duty_r")):
            axis.plot(time, data[column], label=label)
        axes[4].plot(time, data["enc_right_a_physical_edges"], label=f"{label} physical")
        axes[4].plot(time, data["enc_right_a_delivered_edges"], "--", label=f"{label} delivered")
    axes[0].plot(records["Baseline"]["time_s"], records["Baseline"]["reference_r_rad_s"], ":",
                 color="black", label="Firmware reference")
    for axis, ylabel in zip(axes, ("Model speed (rad/s)", "FW estimate (rad/s)", "Model current (A)",
                                  "Observed duty (fraction)", "Right A edges")):
        axis.axvspan(1, 2, color="#e0a000", alpha=.14, label="Fault window")
        axis.set_ylabel(ylabel)
        axis.grid(alpha=.23)
        axis.legend(loc="upper left", ncols=3, fontsize=8)
    axes[-1].set_xlabel("Virtual time (s)")
    figure.suptitle("Right encoder A stuck low from 1 to 2 s · identical firmware")
    figure.savefig(output / "encoder-comparison.png", dpi=150)


def main(output):
    os.environ.setdefault("MPLCONFIGDIR", str(output.parent / ".matplotlib"))
    import matplotlib  # Check the plot dependency before launching the simulations.
    output.mkdir(parents=True)
    elf = output / "example.elf"
    build_example(elf)
    baseline = default_config()
    baseline["scenario"].update(duration_s=3, loads=[], observer="example-v1", encoder_fault_evidence=True)
    faulted = json.loads(json.dumps(baseline))
    faulted["scenario"]["encoder_faults"] = [{"channel": "right.a", "level": 0, "start_s": 1, "end_s": 2}]
    specs = Path(__file__).with_name("checks.json")
    cases = {"Baseline": (baseline, 0), "Faulted": (faulted, 1)}
    records = {}
    exit_status = {}
    for label, (config, expected) in cases.items():
        folder = output / label.lower()
        input_config = output / f"{label.lower()}-input.json"
        write_json(input_config, config)
        proc = subprocess.run([sys.executable, str(ROOT / "setup/runner.py"), "run", "--elf", str(elf),
                               "--config", str(input_config), "--assertions", str(specs),
                               "--output", str(folder)], check=False)
        recording = folder / "recording.csv"
        if proc.returncode != expected:
            raise SystemExit(f"{label} assertions returned {proc.returncode}; expected {expected}.")
        if expected:
            result = json.loads((folder / "assertions.json").read_text())
            activity = next(check for check in result["checks"] if check["metric"] == "encoder_activity")
            if activity["passed"] or activity["delivered"] != 0 or activity["physical"] < 1000:
                raise SystemExit("Expected the faulted right-A signal to stop reaching GPIO while the shaft turns.")
        exit_status[label.lower()] = proc.returncode
        records[label] = read_recording(recording)
    before, after = records.values()
    split = before["time_s"].index(1.0)
    for signal in ("x_m", "y_m", "heading_rad", "wr_rad_s", "ir_A", "fw_total_r"):
        assert before[signal][:split] == after[signal][:split], signal
    clear = after["time_s"].index(2.0)
    assert after["enc_right_a_forced_level"][clear] == -1
    assert after["enc_right_a_delivered_edges"][clear+10] > after["enc_right_a_delivered_edges"][clear]
    assert after["encoder_r"][-1] - after["fw_total_r"][-1] > 10000
    write_json(output / "exit-status.json", exit_status)
    plot(output, records)
    print(f"Baseline passed and faulted expectations failed as intended. Inspect {output / 'encoder-comparison.png'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output.resolve())
