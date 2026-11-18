#!/usr/bin/env bash
set -euo pipefail
output=$(realpath -m "${1:-setup/out/pilot}")
cd "$(dirname "$0")/../.."
mkdir -p "$(dirname "$output")"
mkdir "$output"
# These launches deliberately share no emulator execution or JIT startup time.
python3 tests/setup/check.py 2>&1 | tee "$output/setup.log"
python3 tests/encoder_fault/recovery.py --output "$output/recovery" 2>&1 | tee "$output/recovery.log"
python3 tests/encoder_fault/live_fault_check.py --output "$output/live-fault" 2>&1 | tee "$output/live-fault.log"
python3 tests/setup/live_check.py --output "$output/live" 2>&1 | tee "$output/live.log"
