"""Verify the ST HAL fixture through the external-ELF robot workflow."""
import argparse
import copy
import csv
import hashlib
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "setup"))

from config import PINS, load_config
from runner import read_elf, run_job, write_json

FIRMWARE = ROOT / "firmware/cubef4-hal"
CACHE_WARNING = re.compile(
    r"flash_controller: Unhandled write to offset 0x0\. Unhandled bits: "
    r"\[(8|9|10)\] when writing value 0x[0-9A-Fa-f]+\. Tags: (PRFTEN|ICEN|DCEN) \(0x1\)\."
)


def checked_job(image, config, output, operation):
    result = run_job(image, config, output, operation)
    warnings = []
    for line in (output / "renode.log").read_text().splitlines():
        if "[WARNING]" in line:
            warning = line.split("[WARNING]", 1)[1].strip()
            assert CACHE_WARNING.fullmatch(warning), f"Unexpected emulator warning in {output}: {warning}"
            warnings.append(warning)
    return result, warnings


def trace(path):
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        assert not any(key.startswith(("fw_", "odom_", "estimate_", "reference_"))
                       for key in reader.fieldnames), "Unexpected example observer columns"
        assert "irq_errors" not in reader.fieldnames
        return [{key: float(value) for key, value in row.items()} for row in reader]


def mean(rows, key, start, end):
    return statistics.mean(row[key] for row in rows if start <= row["time_s"] < end)


def check(elf, output):
    config = load_config(FIRMWARE / "scenario.json")
    assert config["scenario"]["observer"] == "none"
    image = read_elf(elf)

    discovery, warnings = checked_job(image, config, output / "discovery", "discover")
    first, idle, *_, active = discovery["snapshots"]
    assert first["time_s"] == 0 and not any(pin["qualified"] for pin in first["pins"].values())
    assert idle["clock_profile_matches"] and active["clock_profile_matches"]
    for pin_name, (_, route, expected_af) in PINS.items():
        pin = active["pins"][pin_name]
        assert pin["qualified"] and pin["peripheral"] == route and pin["af"] == expected_af, pin_name
    measured = {}
    for pin_name in ("PA0", "PA1"):
        assert idle["pins"][pin_name]["activity"]["duty"] == 0
        observed = active["pins"][pin_name]["activity"]
        assert observed["kind"] == "periodic" and abs(observed["period_s"] - 0.001) < 2.1e-9
        measured[pin_name] = observed["period_s"]

    loaded, _ = checked_job(image, config, output / "loaded", "run")
    reproduced_config = load_config(output / "loaded/config.json")
    repeated, _ = checked_job(image, reproduced_config, output / "repeat", "run")
    unloaded = copy.deepcopy(config)
    unloaded["scenario"]["loads"] = []
    baseline, _ = checked_job(image, unloaded, output / "unloaded", "run")
    assert loaded["elf_sha256"] == repeated["elf_sha256"] == baseline["elf_sha256"]
    assert loaded["samples"] == repeated["samples"] == baseline["samples"] == 10400
    loaded_path, repeat_path = (output / name / "recording.csv" for name in ("loaded", "repeat"))
    assert loaded_path.read_bytes() == repeat_path.read_bytes(), "Fresh runs differ"
    data = trace(loaded_path)
    unloaded_data = trace(output / "unloaded/recording.csv")

    # The firmware gates GPIO on startup, clock, hard-FP and HAL_Delay checks.
    assert data[0]["dir_l"] == data[0]["dir_r"] == -1, "Discovery state leaked into run"
    direction_high = next(row["time_s"] for row in data if row["dir_l"] == row["dir_r"] == 1)
    first_pwm = next(row["time_s"] for row in data if row["duty_l"] > 0 and row["duty_r"] > 0)
    assert 0.006 <= direction_high <= 0.012, direction_high
    assert 0.205 <= first_pwm <= 0.215, first_pwm

    settled_speeds = {}
    for window, expectation in [
        ((1.70, 1.95), (10, 10)),
        ((4.10, 4.35), (-5, 5)),
        ((6.70, 6.95), (6, 10)),
        ((9.30, 9.55), (-8, -8)),
    ]:
        speeds = tuple(mean(data, key, *window) for key in ("wl_rad_s", "wr_rad_s"))
        assert all(abs(actual - target) < 0.05 * abs(target) for actual, target in zip(speeds, expectation)), speeds
        settled_speeds[str(window[0])] = speeds
    # Settled turn duty only needs to exceed one compare count on each channel.
    assert all(row["dir_l"] < 0 < row["dir_r"] and min(row["duty_l"], row["duty_r"]) > 0.001
               for row in data if 4.10 <= row["time_s"] < 4.35)
    curve_duty = [mean(data, key, 6.70, 6.95) for key in ("duty_l", "duty_r")]
    assert curve_duty[1] - curve_duty[0] > 0.005
    assert all(row["unsafe_switches"] == 0 for row in data)
    for row in data:
        assert row["tim3_counter"] == int(row["encoder_l"]) % 65536
        assert row["tim4_counter"] == int(row["encoder_r"]) % 65536

    assert all(a == b for a, b in zip(data, unloaded_data) if a["time_s"] < 0.8)
    duty_delta = mean(data, "duty_r", 1.10, 1.35) - mean(unloaded_data, "duty_r", 1.10, 1.35)
    current_delta = mean(data, "ir_A", 1.10, 1.35) - mean(unloaded_data, "ir_A", 1.10, 1.35)
    speed_drop = mean(unloaded_data, "wr_rad_s", 0.85, 1.10) - mean(data, "wr_rad_s", 0.85, 1.10)
    assert duty_delta > 0.02 and current_delta > 0.1 and speed_drop > 0.1
    encoder_change = next(a["time_s"] for a, b in zip(data, unloaded_data) if a["tim4_counter"] != b["tim4_counter"])
    duty_change = next(a["time_s"] for a, b in zip(data, unloaded_data) if abs(a["duty_r"] - b["duty_r"]) > 0.0005)
    assert 0.8 < encoder_change <= duty_change
    write_json(output / "summary.json", {
        "elf_sha256": loaded["elf_sha256"], "samples_per_run": loaded["samples"],
        "recording_sha256": hashlib.sha256(loaded_path.read_bytes()).hexdigest(),
        "repeat_identical": True, "qualified_pins": list(PINS),
        "pwm_period_s": measured, "initial_direction_high_s": direction_high,
        "first_nonzero_pwm_s": first_pwm, "settled_wheel_speed_rad_s": settled_speeds,
        "mean_curve_duty_left_right": curve_duty,
        "load_right_duty_delta": duty_delta, "load_right_current_delta_A": current_delta,
        "load_right_speed_drop_rad_s": speed_drop, "first_changed_right_counter_s": encoder_change,
        "first_changed_right_pwm_s": duty_change, "flash_cache_prefetch_warnings": warnings,
        "unsafe_direction_switches": int(data[-1]["unsafe_switches"]),
        "final_pose_m_rad": [data[-1][key] for key in ("x_m", "y_m", "heading_rad")],
    })
    print(f"PASS STM32CubeF4 HAL fixture: {output / 'summary.json'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, default=FIRMWARE / "out/robot.elf")
    parser.add_argument("--output", type=Path, required=True, help="New directory for traces and report")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new output directory.")
    check(args.elf, args.output)


if __name__ == "__main__":
    main()
