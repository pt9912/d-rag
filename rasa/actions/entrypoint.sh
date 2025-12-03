#!/bin/bash
set -euo pipefail

export PIP_TARGET=/tmp/pip-target-actions
export PYTHONPATH=/:/tmp/pip-target-actions:${PYTHONPATH:-}
export PIP_CACHE_DIR=/tmp/pip-cache-actions
export XDG_CONFIG_HOME=${XDG_CONFIG_HOME:-/tmp/.config}
export HOME=${HOME:-/tmp}

mkdir -p "$XDG_CONFIG_HOME"
rm -rf "$PIP_TARGET" "$PIP_CACHE_DIR" || true
pip install --no-cache-dir --target "$PIP_TARGET" /actions

exec rasa run actions --port 5055 --actions actions
