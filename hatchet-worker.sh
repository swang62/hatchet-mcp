#!/bin/bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "$0")"
exec uv run python src/hatchet_worker/worker.py
