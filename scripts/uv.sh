#!/bin/sh
# Keep project environments and dependency caches inside the project workspace.
set -eu
project_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
export UV_PROJECT_ENVIRONMENT="$project_root/.bensz-api/.venv"
export UV_CACHE_DIR="$project_root/.bensz-api/uv-cache"
unset VIRTUAL_ENV
# uv creates Git ignore markers and checkout metadata inside its cache.
# Project policy permits Git metadata only in the root repository.
cleanup_git_metadata() {
    if [ -d "$UV_CACHE_DIR" ]; then
        find "$UV_CACHE_DIR" -name .git -prune -exec rm -rf {} +
    fi
}
trap cleanup_git_metadata 0
uv "$@"
