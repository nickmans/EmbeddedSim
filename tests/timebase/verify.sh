#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 2 ]]; then
  printf 'Usage: bash tests/timebase/verify.sh ORIGINAL_ELF NEW_OUTPUT_DIRECTORY\n' >&2
  exit 2
fi
elf=$(realpath "$1")
output=$(realpath -m "$2")
cd "$(dirname "$0")/../.."
mkdir -p "$(dirname "$output")"
mkdir "$output"
bash experiments/renode-smoke/bootstrap.sh
if python3 tests/timebase/check.py --legacy --output "$output/hal-before" >"$output/hal-before.log" 2>&1; then
  printf 'Expected the legacy SysTick configuration to fail the HAL timing assertion.\n' >&2
  exit 1
fi
grep -F 'AssertionError: HAL_Delay is not 10–11 ms in virtual time' "$output/hal-before.log"
python3 tests/timebase/check.py --output "$output/hal-after"
python3 tests/third-party-pwm/check.py --legacy-clock --elf "$elf" --output "$output/original-before"
python3 tests/third-party-pwm/check.py --elf "$elf" --output "$output/original-after"
python3 setup/runner.py discover --config setup/pwm-signal.json --elf "$elf" \
  --seconds 0.02 --output "$output/discovery"
python3 setup/runner.py discover --config setup/default.json --elf "$elf" \
  --seconds 0.02 --output "$output/robot-profile-mismatch"
if python3 setup/runner.py run --config setup/pwm-signal.json --elf "$elf" \
    --output "$output/rejected-run" >"$output/rejected-run.log" 2>&1; then
  printf 'Expected the signal-only profile to reject a robot simulation run.\n' >&2
  exit 1
fi
grep -F 'supports discovery only' "$output/rejected-run.log"

python3 - "$output" <<'PY'
import json
from pathlib import Path
import sys

out = Path(sys.argv[1])
def load(path):
    return json.loads((out / path).read_text())

report = load("discovery/result.json")
final = report["snapshots"][-1]
assert final["clock_profile_matches"] and not report.get("diagnostics")
assert final["clocks"]["hclk_hz"] == 168_000_000
assert final["pins"]["PA0"]["timer"]["counter_hz"] == 1_000_000
assert final["pins"]["PA2"]["timer"]["capture_interrupt"]
pwm = final["pins"]["PA6"]
assert abs(pwm["observed"]["period_s"] - pwm["expected_period_s"]) < 4e-9
assert pwm["observed"]["duty"] > .999
assert not final["pins"]["PE5"]["qualified"]
assert "pwm-signal-pll168-v1" in load("robot-profile-mismatch/result.json")["diagnostics"][0]
before, after = load("original-before/summary.json"), load("original-after/summary.json")
assert report["elf_sha256"] == before["sha256"] == after["sha256"]
assert before["phases"] == after["phases"] and before["pre_input_reverse"] == after["pre_input_reverse"]
print(f"PASS normal external-ELF discovery and profile diagnostics. Evidence in {out}")
PY
