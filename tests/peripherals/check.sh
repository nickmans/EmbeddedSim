#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
timeout 180 bash experiments/renode-smoke/bootstrap.sh
timeout 200 python3 tests/peripherals/run.py
export RENODE_QUALIFIED=1
timeout 65 python3 experiments/renode-smoke/verify.py
timeout 50 python3 experiments/renode-smoke/gdb_check.py
timeout 65 python3 experiments/renode-smoke/limitations.py
