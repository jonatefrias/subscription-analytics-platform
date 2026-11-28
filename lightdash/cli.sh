#!/bin/sh
# Runs the pinned Lightdash CLI against the local instance, from the dbt project directory.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/lightdash/.env" ] && set -a && . "$ROOT/lightdash/.env" && set +a
export LAKE_DIR="${LAKE_DIR:-$ROOT/data/lake}" DBT_PROFILES_DIR="$ROOT/transform" CI=true PATH="$ROOT/.venv/bin:$PATH"
cd "$ROOT/transform"
exec npx -y @lightdash/cli@3.434.0 "$@"
