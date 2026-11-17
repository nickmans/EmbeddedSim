#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
timeout 180 bash experiments/renode-smoke/bootstrap.sh
export MPLCONFIGDIR=/workspace/.runtime-config/matplotlib
export PYTHONPATH="/workspace/tools/embedded-sim-python${PYTHONPATH:+:$PYTHONPATH}"
if ! python3 -c 'import numpy,matplotlib; assert numpy.__version__=="2.3.5" and matplotlib.__version__=="3.10.8"'; then
 timeout 240 python3 -m pip install --only-binary=:all: --upgrade --target /workspace/tools/embedded-sim-python -r tests/closed_loop/requirements.txt
fi
timeout 120 python3 tests/robot/qualify.py
timeout 1800 python3 tests/robot/run.py
timeout 2000 bash tests/closed_loop/check.sh
