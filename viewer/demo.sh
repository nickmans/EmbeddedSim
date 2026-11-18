#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash experiments/renode-smoke/bootstrap.sh
export MPLCONFIGDIR=/workspace/.runtime-config/matplotlib
export PYTHONPATH="/workspace/tools/embedded-sim-python${PYTHONPATH:+:$PYTHONPATH}"
if ! python3 -c 'import numpy,matplotlib; assert numpy.__version__=="2.3.5" and matplotlib.__version__=="3.10.8"'; then
  python3 -m pip install --only-binary=:all: --upgrade --target /workspace/tools/embedded-sim-python \
    -r tests/closed_loop/requirements.txt
fi
python3 tests/robot/run.py --case main
port=${1:-8765}
printf 'Open http://127.0.0.1:%s/viewer/\n' "$port"
exec python3 -m http.server --bind 127.0.0.1 "$port"
