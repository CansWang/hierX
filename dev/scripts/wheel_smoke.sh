#!/usr/bin/env bash
# Installed-wheel smoke test OUTSIDE the checkout: build the wheel, install it into a fresh venv, then from the
# work directory (never the checkout) assert with isolated Python (-I: no cwd on sys.path) that the IMPORTED hx is
# the venv's copy and carries its package data (Xyce inventory, schemas, viewer assets); then from unrelated
# directories extract a copied netlist deck, query a net and export a page. Exit non-zero on the first failure.
# Usage: dev/scripts/wheel_smoke.sh [WORKDIR]   (default: a fresh mktemp directory; printed at the end)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="${1:-$(mktemp -d /tmp/hx-wheel-smoke.XXXXXX)}"
PY="${PYTHON:-python3}"
mkdir -p "$WORK"
WORK="$(cd "$WORK" && pwd)"                        # absolute: the package-data check below changes directory into it
echo "== build wheel"
"$PY" -m pip wheel --no-deps --no-build-isolation -w "$WORK/wheels" "$REPO" >/dev/null 2>&1 || "$PY" -m pip wheel --no-deps -w "$WORK/wheels" "$REPO" >/dev/null
WHEEL="$(ls "$WORK"/wheels/hx-*.whl | head -1)"
echo "   $WHEEL"
echo "== fresh venv"
"$PY" -m venv "$WORK/venv"
"$WORK/venv/bin/python" -m pip install --quiet --upgrade pip
"$WORK/venv/bin/python" -m pip install --quiet "$WHEEL"
HX="$WORK/venv/bin/hx"
echo "== package data present (hx imported from the fresh venv, not the checkout)"
cd "$WORK"
"$WORK/venv/bin/python" -I - <<'PY'
import importlib.resources as r, importlib.util, os, sys
import hx
where = os.path.realpath(os.path.dirname(hx.__file__))
venv = os.path.realpath(sys.prefix)
if not where.startswith(venv + os.sep):
    sys.exit(f"hx imported from {where}, not from the fresh venv {venv}")
pkg = r.files("hx")
need = ["netlist/xyce_devices.json", "schema/hx-1.schema.json", "schema/hx-2.schema.json", "schema/hx-3.schema.json",
        "schema/hx-4.schema.json", "schema/hx-arch-1.schema.json", "viewer/app.js", "viewer/circuit.js", "viewer/patch.js", "viewer/index.html", "viewer/style.css",
        "architecture/index.html", "architecture/diagram.js", "viewer/vendor/elk.bundled.js", "viewer/vendor/elk-LICENSE.md"]
missing = [n for n in need if not pkg.joinpath(n).is_file()]
vendor = [p.name for p in pkg.joinpath("viewer/vendor").iterdir()] if pkg.joinpath("viewer/vendor").is_dir() else []
if missing or not vendor:
    sys.exit(f"missing package data: {missing or 'viewer/vendor/*'}")
retired = ["contracts", "schema/hx-contract-1.schema.json", "schema/hx-bindings-1.schema.json", "schema/hx-projection-1.schema.json"]
leaked = [name for name in retired if pkg.joinpath(name).exists()]
if leaked or importlib.util.find_spec("hx.contracts") is not None:
    sys.exit(f"retired TOML feature leaked into wheel: {leaked}")
print("   ok:", len(need), "data files +", sum(n.endswith(".js") for n in vendor), "vendored libraries (", len(vendor), "vendor files), imported from", where)
PY
echo "== retired contract command is unavailable"
if "$HX" contract --help >"$WORK/retired-command.log" 2>&1; then
  echo "retired contract command is still available" >&2
  exit 1
else
  status=$?
  [ "$status" -eq 2 ] || { cat "$WORK/retired-command.log" >&2; exit 1; }
fi
"$WORK/venv/bin/python" -I - "$WORK/retired-command.log" <<'PY'
from pathlib import Path
import sys
message = Path(sys.argv[1]).read_text()
assert "invalid choice: 'contract'" in message and "Traceback" not in message, message
print("   normal unknown-command exit 2; retired package and schemas absent")
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
echo "== D2 architecture from an unrelated directory"
mkdir -p "$WORK/architecture"
cat >"$WORK/architecture/design.d2" <<'D2'
producer: {sample: u32 {class: hx-output}}
consumer: {sample: u32 {class: hx-input}}
producer.sample -> consumer.sample: sample
D2
cd "$WORK/architecture"
"$HX" arch inspect design.d2 --json >"$WORK/architecture.json"
"$HX" arch export design.d2 -o "$WORK/architecture.html" >/dev/null
"$WORK/venv/bin/python" -I - "$WORK/architecture.json" "$WORK/architecture.html" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
assert data["schema"] == "hx-arch/1" and data["valid"]
assert len(data["blocks"]) == 2 and len(data["ports"]) == 2 and len(data["connections"]) == 1
html = Path(sys.argv[2]).read_text()
assert "hx-elk-license" in html and "hxArchitecture" in html and "/static/" not in html
print("   architecture inspection and offline HTML assets passed")
PY
echo "== wheel smoke passed: $WORK"
