"""Evaluate version 1 robot outcomes against an authoritative recording."""
import argparse
from bisect import bisect_left
import csv
import json
import math
from pathlib import Path
import sys

from config import SetupError, fault_channel, fields, number

METRICS = {
    "tracking_mae": ("rad/s", "model wheel speed and firmware reference"),
    "peak_current": ("A", "model motor current"),
    "pwm_saturation": ("s", "observed PWM duty"),
    "encoder_activity": ("edges", "physical encoder and MCU GPIO transitions"),
}


def read_recording(path):
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames
        if not headers or "time_s" not in headers or len(headers) != len(set(headers)):
            raise SetupError("Expected unique recording columns including time_s.")
        data = {key: [] for key in headers}
        for index, row in enumerate(reader, 2):
            if None in row or None in row.values():
                raise SetupError(f"Recording row {index} has the wrong field count.")
            for key, raw in row.items():
                try:
                    value = float(raw)
                except ValueError as error:
                    raise SetupError(f"Recording row {index}: {key} is not numeric.") from error
                if not math.isfinite(value):
                    raise SetupError(f"Recording row {index}: {key} is not finite.")
                data[key].append(value)
    times = data["time_s"]
    if len(times) < 2 or any(b <= a for a, b in zip(times, times[1:])):
        raise SetupError("Expected at least two strictly increasing recording timestamps in seconds.")
    return data


def signal(data, key):
    if key not in data:
        raise SetupError(f"Missing required signal {key}; check the observer or encoder evidence configuration.")
    return data[key]


def inspect(data, check):
    if not isinstance(check, dict) or check.get("metric") not in tuple(METRICS):
        raise SetupError("Unknown assertion metric.")
    metric = check["metric"]
    common = ("name", "metric", "start_s", "end_s")
    if metric == "encoder_activity":
        fields(check, common + ("channel", "min_physical_edges", "min_delivered_edges", "max_delivered_edges"), metric)
    else:
        extra = ("duty_fraction",) if metric == "pwm_saturation" else ()
        fields(check, common + ("wheel", "max") + extra, metric)
    name = check["name"]
    if not isinstance(name, str) or not name.strip():
        raise SetupError("Assertion name must be nonempty text.")
    times = data["time_s"]
    start, end = (number(check[key], times[0], times[-1], key) for key in ("start_s", "end_s"))
    if end <= start:
        raise SetupError(f"{name}: assertion interval must have positive duration.")
    first, last = (bisect_left(times, t) for t in (start, end))
    if metric == "encoder_activity":
        return encoder_activity(data, check, first, last)
    if check["wheel"] not in ("left", "right"):
        raise SetupError(f"{name}: wheel must be left or right.")
    side = check["wheel"][0]
    limit = number(check["max"], 0, math.inf, f"{name} maximum")
    intervals = [(i, min(end, times[i+1]) - max(start, times[i]))
                 for i in range(max(0, first-1), last) if min(end, times[i+1]) > max(start, times[i])]
    if metric == "tracking_mae":
        speed = signal(data, f"w{side}_rad_s")
        reference = signal(data, f"reference_{side}_rad_s")
        value = sum(abs(speed[i] - reference[i]) * dt for i, dt in intervals) / (end - start)
    elif metric == "peak_current":
        current = signal(data, f"i{side}_A")
        value = max(abs(current[i]) for i, _ in intervals)
    else:
        duty = signal(data, f"duty_{side}")
        threshold = number(check["duty_fraction"], 0, 1, "PWM duty threshold (fraction)")
        if any(not 0 <= measured <= 1 for measured in duty):
            raise SetupError(f"duty_{side} must contain fractions in [0, 1].")
        value = sum(dt for i, dt in intervals if duty[i] >= threshold)
    units, source = METRICS[metric]
    return {"name": name, "metric": metric, "source": source, "value": value,
            "unit": units, "max": limit, "passed": value <= limit}


def encoder_activity(data, check, first, last):
    name = check["name"]
    fault_channel(check["channel"])
    channel = check["channel"].replace(".", "_")
    if data["time_s"][first] != check["start_s"] or data["time_s"][last] != check["end_s"]:
        raise SetupError(f"{name}: encoder activity interval endpoints must match recorded sample times.")
    counts = {}
    for layer in ("physical", "delivered"):
        values = signal(data, f"enc_{channel}_{layer}_edges")
        if any(value < 0 or not value.is_integer() for value in values) or any(b < a for a, b in zip(values, values[1:])):
            raise SetupError(f"{name}: {layer} edge counts must be nondecreasing nonnegative integers.")
        counts[layer] = int(values[last] - values[first])
    low = number(check["min_delivered_edges"], 0, math.inf, "Minimum delivered edges")
    high = number(check["max_delivered_edges"], low, math.inf, "Maximum delivered edges")
    moving = number(check["min_physical_edges"], 1, math.inf, "Minimum physical edges")
    if any(type(value) != int for value in (low, high, moving)):
        raise SetupError("Encoder edge limits must be integers.")
    return {"name": name, "metric": "encoder_activity", "source": METRICS["encoder_activity"][1],
            "unit": "edges", "physical": counts["physical"], "delivered": counts["delivered"],
            "min_physical": moving, "min_delivered": low, "max_delivered": high,
            "passed": counts["physical"] >= moving and low <= counts["delivered"] <= high}


def evaluate(recording, spec, output):
    fields(spec, ("version", "checks"), "Assertion suite")
    checks = spec["checks"]
    if type(spec["version"]) != int or spec["version"] != 1 or not isinstance(checks, list) or not 1 <= len(checks) <= 64:
        raise SetupError("Expected assertion version 1 with 1–64 checks.")
    data = read_recording(recording)
    results = [inspect(data, check) for check in checks]
    passed = all(result["passed"] for result in results)
    output.mkdir(parents=True, exist_ok=True)
    report = {"version": 1, "passed": passed, "checks": results}
    (output / "assertions.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = []
    for result in results:
        if result["metric"] == "encoder_activity":
            detail = (f'{result["physical"]} physical, {result["delivered"]} delivered edges '
                      f'(expected physical ≥ {result["min_physical"]}, delivered {result["min_delivered"]}–{result["max_delivered"]})')
        else:
            detail = f'{result["value"]:.5g} {result["unit"]} (maximum {result["max"]:g})'
        lines.append(f'{"PASS" if result["passed"] else "FAIL"} {result["name"]} — {detail}')
    summary = "\n".join(lines) + "\n"
    (output / "assertions.txt").write_text(summary)
    print(summary, end="")
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--checks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return run_assertions(args.recording, args.checks, args.output)


def run_assertions(recording, checks, output):
    try:
        return 0 if evaluate(recording, json.loads(checks.read_text()), output) else 1
    except (ValueError, OSError, csv.Error) as error:
        print(f"Assertion input error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
