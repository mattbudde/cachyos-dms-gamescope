#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $EUID -eq 0 ]]; then
    printf '%s\n' 'Run tests as an unprivileged user; root test mode is intentionally disabled.' >&2
    exit 1
fi

cache_dir="$(mktemp -d /tmp/cachyos-gamemode-pycache.XXXXXX)"
trap 'rm -rf -- "$cache_dir"' EXIT
export PYTHONPYCACHEPREFIX="$cache_dir"

bash -n "$project_dir/install.sh" "$project_dir/uninstall.sh" \
    "$project_dir/src/steamos-session-select" \
    "$project_dir/src/start-gamescope-session"
python3 -m py_compile \
    "$project_dir/src/cachyos-sessionctl" \
    "$project_dir/src/cachyos-session-handoff" \
    "$project_dir/tests/test_sessionctl.py" \
    "$project_dir/tests/test_assets.py"
python3 -m unittest discover -v -s "$project_dir/tests" -p 'test_*.py'

printf '%s\n' 'All checks passed.'
