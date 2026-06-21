#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
exec uv run python src/hatchet_worker/worker.py
