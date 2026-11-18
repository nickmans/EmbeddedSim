"""Compare encoder reconnection with the stock controller's reference held at 10 rad/s."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "setup"))
from assertions import read_recording
from config import default_config
from runner import build_example, write_json

FAULT = {"channel": "right.a", "level": 0, "start_s": .95, "end_s": 1.2}
WINDOWS = {"normal": (.85, .95), "fault": (1.0, 1.175), "reconnection": (1.2, 1.3),
           "unchanged_reference": (1.65, 1.9), "commanded_stop": (2.05, 2.65)}
EXPECTED_FAILURES = {"Tracking through fault window", "Shaft activity reaches GPIO through fault window"}
RECOVERY_CHECK = "Tracking after reconnection under unchanged reference"


def derived(data):
    data["signed_pwm"] = [duty * direction for duty, direction in zip(data["duty_r"], data["dir_r"])]
    data["count_gap"] = [int(physical - firmware) for physical, firmware in zip(data["encoder_r"], data["fw_total_r"])]
    data["position_error_m"] = [math.hypot(x - ox, y - oy) for x, y, ox, oy in
                                zip(data["x_m"], data["y_m"], data["odom_x_m"], data["odom_y_m"])]


def metrics(data, start, end):
    times = data["time_s"]
    first, last = times.index(start), times.index(end)
    span = slice(first, last)
    speed = data["wr_rad_s"][span]
    estimate = data["estimate_r_rad_s"][span]
    reference = data["reference_r_rad_s"][span]
    mean = lambda values: sum(values) / len(speed)  # All contiguous samples are 1 ms apart.
    return {
        "start_s": start, "end_s": end,
        "model_speed_range_rad_s": [min(speed), max(speed)],
        "firmware_estimate_range_rad_s": [min(estimate), max(estimate)],
        "tracking_mae_rad_s": mean(abs(a-b) for a,b in zip(speed, reference)),
        "estimate_mae_rad_s": mean(abs(a-b) for a,b in zip(speed, estimate)),
        "signed_pwm_range": [min(data["signed_pwm"][span]), max(data["signed_pwm"][span])],
        "peak_abs_model_current_A": max(map(abs, data["ir_A"][span])),
        "physical_A_edges": int(data["enc_right_a_physical_edges"][last] - data["enc_right_a_physical_edges"][first]),
        "delivered_A_edges": int(data["enc_right_a_delivered_edges"][last] - data["enc_right_a_delivered_edges"][first]),
        "final_physical_minus_firmware_counts": data["count_gap"][last],
        "final_position_error_m": data["position_error_m"][last],
    }


def plot(output, recordings):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(7, 1, figsize=(10, 13), sharex=True, layout="constrained")
    signals = [("wr_rad_s", "Model speed (rad/s)"), ("estimate_r_rad_s", "FW speed (rad/s)"),
               ("signed_pwm", "PWM duty × direction"), ("ir_A", "Model current (A)"),
               ("enc_right_a_physical_edges", "Cumulative A edges"), ("count_gap", "Physical − FW counts"),
               ("position_error_m", "Position error (m)")]
    baseline = recordings["Baseline"]
    axes[0].plot(baseline["time_s"], baseline["reference_r_rad_s"], "k:", label="Command")
    for label, data in recordings.items():
        for axis, (signal, ylabel) in zip(axes, signals):
            line, = axis.plot(data["time_s"], data[signal], label=label)
            axis.set_ylabel(ylabel)
            if signal == "enc_right_a_physical_edges":
                line.set_label(f"{label} physical")
                axis.plot(data["time_s"], data["enc_right_a_delivered_edges"], "--", color=line.get_color(),
                          label=f"{label} GPIO")
    stop = next(time for time, reference in zip(baseline["time_s"], baseline["reference_r_rad_s"])
                if time > FAULT["end_s"] and reference == 0)
    for i, axis in enumerate(axes):
        axis.axvspan(FAULT["start_s"], FAULT["end_s"], color="#db8d00", alpha=.2, label="Fault active" if i == 0 else None)
        axis.axvspan(*WINDOWS["reconnection"], color="#3084bf", alpha=.12, label="Immediate response" if i == 0 else None)
        axis.axvline(stop, color="gray", linestyle=":", label="Zero command" if i == 0 else None)
        axis.grid(alpha=.25)
        axis.legend(loc="upper left", fontsize=8, ncols=3)
    axes[-1].set_xlabel("Virtual time (s)")
    figure.suptitle("Right A stuck low, reconnected with a 10 rad/s command, then commanded stop")
    figure.savefig(output / "encoder-recovery.png", dpi=140)


def run(output):
    output.mkdir(parents=True)
    os.environ.setdefault("MPLCONFIGDIR", str(output / ".matplotlib"))
    elf = output / "example.elf"
    build_example(elf)
    config = default_config()
    config["scenario"].update(duration_s=2.7, loads=[], observer="example-v1", encoder_fault_evidence=True)
    suite = Path(__file__).with_name("recovery-checks.json")
    recordings, summary = {}, {}
    for label, faulted in (("Baseline", False), ("Faulted", True)):
        if faulted:
            config["scenario"]["encoder_faults"] = [FAULT]
        folder = output / label.lower()
        input_config = output / f"{label.lower()}-input.json"
        write_json(input_config, config)
        result = subprocess.run([sys.executable, str(ROOT / "setup/runner.py"), "run", "--elf", str(elf),
                                 "--config", str(input_config), "--assertions", str(suite), "--output", str(folder)])
        assert result.returncode == int(faulted), f"{label}: unexpected runner exit {result.returncode}"
        checks = json.loads((folder / "assertions.json").read_text())["checks"]
        failed = {check["name"] for check in checks if not check["passed"]}
        # Recovery is an empirical outcome. Only the deliberately violated healthy-feedback checks are required failures.
        assert failed - ({RECOVERY_CHECK} if faulted else set()) == (EXPECTED_FAILURES if faulted else set()), failed
        data = read_recording(folder / "recording.csv")
        reference = data["reference_r_rad_s"]
        times = data["time_s"]
        assert set(reference[times.index(WINDOWS["normal"][0]):times.index(1.9)+1]) == {10}
        assert set(reference[times.index(2.05):]) == {0}
        masks = data["enc_right_a_forced_level"]
        transitions = [{"at_s": times[i], "mask": int(b)} for i, (a,b) in enumerate(zip(masks, masks[1:]), 1) if a != b]
        assert transitions == ([{"at_s": FAULT["start_s"], "mask": 0}, {"at_s": FAULT["end_s"], "mask": -1}] if faulted else [])
        reference_changes = [{"at_s": times[i], "reference_rad_s": b}
                             for i, (a, b) in enumerate(zip(reference, reference[1:]), 1) if a != b]
        derived(data)
        recordings[label] = data
        summary[label.lower()] = {"assertion_exit": result.returncode, "mask_transitions": transitions,
                                   "reference_changes": reference_changes, "checks": checks,
                                   "recording_sha256": hashlib.sha256((folder / "recording.csv").read_bytes()).hexdigest(),
                                   "windows": {name: metrics(data, *window) for name, window in WINDOWS.items()}}
    baseline, faulted = recordings.values()
    for column in ("time_s", "reference_l_rad_s", "reference_r_rad_s"):
        assert baseline[column] == faulted[column], f"Unequal inputs: {column}"
    before = baseline["time_s"].index(FAULT["start_s"])
    assert all(series[:before] == faulted[key][:before] for key, series in baseline.items())
    assert summary["faulted"]["windows"]["fault"]["delivered_A_edges"] == 0
    assert summary["faulted"]["windows"]["reconnection"]["delivered_A_edges"] > 0
    summary["elf_sha256"] = hashlib.sha256(elf.read_bytes()).hexdigest()
    write_json(output / "recovery-results.json", summary)
    plot(output, recordings)
    print(f"Inspect {output / 'encoder-recovery.png'} and recovery-results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
