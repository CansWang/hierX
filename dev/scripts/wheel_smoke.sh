#!/usr/bin/env bash
# Installed-wheel smoke test OUTSIDE the checkout: build the wheel, install it into a fresh venv, then from an
# unrelated directory extract a copied netlist deck, query a net, export a page, and assert the package data
# (Xyce inventory, schemas, viewer assets) is present. Exit non-zero on the first failure.
# Usage: dev/scripts/wheel_smoke.sh [WORKDIR]   (default: a fresh mktemp directory; printed at the end)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="${1:-$(mktemp -d /tmp/hx-wheel-smoke.XXXXXX)}"
PY="${PYTHON:-python3}"
mkdir -p "$WORK"
echo "== build wheel"
"$PY" -m pip wheel --no-deps --no-build-isolation -w "$WORK/wheels" "$REPO" >/dev/null 2>&1 || "$PY" -m pip wheel --no-deps -w "$WORK/wheels" "$REPO" >/dev/null
WHEEL="$(ls "$WORK"/wheels/hx-*.whl | head -1)"
echo "   $WHEEL"
echo "== fresh venv"
"$PY" -m venv "$WORK/venv"
"$WORK/venv/bin/python" -m pip install --quiet --upgrade pip
"$WORK/venv/bin/python" -m pip install --quiet "$WHEEL"
HX="$WORK/venv/bin/hx"
echo "== package data present"
"$WORK/venv/bin/python" - <<'PY'
import importlib.resources as r, sys
pkg = r.files("hx")
need = ["netlist/xyce_devices.json", "schema/hx-1.schema.json", "schema/hx-2.schema.json", "schema/hx-3.schema.json",
        "schema/hx-4.schema.json", "viewer/app.js", "viewer/circuit.js", "viewer/patch.js", "viewer/index.html", "viewer/style.css"]
missing = [n for n in need if not pkg.joinpath(n).is_file()]
vendor = [p.name for p in pkg.joinpath("viewer/vendor").iterdir()] if pkg.joinpath("viewer/vendor").is_dir() else []
if missing or not vendor:
    sys.exit(f"missing package data: {missing or 'viewer/vendor/*'}")
print("   ok:", len(need), "files +", len(vendor), "vendored viewer libraries")
PY
echo "== commands from an unrelated directory"
cp -r "$REPO/tests/fixtures/spice/ota" "$WORK/ota"
cd "$WORK/ota"
"$HX" --help >/dev/null
"$HX" extract ota.sp:. --dialect ngspice --root . -o "$WORK/ota.json" | tail -1
"$HX" netlist net outa --graph "$WORK/ota.json" | head -1
"$HX" netlist uses /five_t_opamp --kind definition --graph "$WORK/ota.json" | head -1
"$HX" export "$WORK/ota.json" -o "$WORK/ota.html" >/dev/null && test -s "$WORK/ota.html"
cp -r "$REPO/tests/fixtures/xyce" "$WORK/xyce"
cd "$WORK/xyce"
"$HX" extract analog.cir:. --dialect xyce --root . -o "$WORK/analog.json" | tail -1
if command -v rust-analyzer >/dev/null 2>&1 || [ -x "$HOME/.cargo/bin/rust-analyzer" ]; then
  cp -r "$REPO/tests/fixtures/rust" "$WORK/rust" && rm -rf "$WORK/rust/target" && cd "$WORK/rust"
  PATH="$HOME/.cargo/bin:$PATH" "$HX" extract src/lib.rs:app_run --root . -o "$WORK/rust.json" | tail -1
else
  echo "   (rust-analyzer absent: Rust extraction skipped)"
fi
echo "== wheel smoke passed: $WORK"
