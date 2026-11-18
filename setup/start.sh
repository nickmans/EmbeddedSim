#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash experiments/renode-smoke/bootstrap.sh
exec python3 setup/server.py "$@"
