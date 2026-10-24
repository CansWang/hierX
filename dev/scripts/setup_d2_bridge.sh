#!/usr/bin/env bash
# Explicit setup only: bootstrap a user-local Go SDK when needed, then build.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
hx_python="${PYTHON:-python3}"
command -v "$hx_python" >/dev/null || { echo 'Python 3.10+ is required for Hx bridge setup' >&2; exit 2; }
"$hx_python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo 'Python 3.10+ is required for Hx bridge setup' >&2; exit 2; }
exec "$hx_python" "$repo/dev/scripts/setup_d2_bridge.py" "$@"
