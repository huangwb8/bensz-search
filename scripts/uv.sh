#!/bin/sh
# Keep project environments and dependency caches inside the project workspace.
set -eu
project_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
export UV_PROJECT_ENVIRONMENT="$project_root/.bensz-api/.venv"
export UV_CACHE_DIR="$project_root/.bensz-api/uv-cache"
unset VIRTUAL_ENV
# uv requires a lockfile beside pyproject.toml; expose it only while uv runs.
exec python3 "$project_root/scripts/uv_lock.py" "$@"
