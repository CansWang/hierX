#!/usr/bin/env bash
set -euo pipefail
example_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$example_dir/../.." && pwd)"
if [[ -n "${PYTHON:-}" ]]; then
    example_python="$PYTHON"
elif [[ -x "$repo_dir/.venv/bin/python" ]]; then
    example_python="$repo_dir/.venv/bin/python"
else
    example_python=python3
fi
exec "$example_python" "$example_dir/run.py" "$@"
