# hx — function-scoped structure extractor

`hx` answers one question quickly: **starting from this function, what does the
code look like?** It walks the call hierarchy to a chosen depth and records,
for every function reached, its signature, parameters tagged in/out, the
resolved types behind them (structs with field offsets, typedef chains,
enums), the globals it touches, and every call edge, including calls hidden
behind macros and calls through function pointers.

The output is a schema-versioned JSON graph. It is designed to be regenerated
after every AI-agent editing session and then **diffed and viewed** instead of
reading the agent's narration. IDs are stable across regeneration, so notes
you attach later survive.

Status: **Phase 3** done — C/C++ (libclang), SystemVerilog/Verilog (verilator),
Rust (rust-analyzer) and Python (pyright) frontends, plus the browser viewer with
editable annotations and live reload. Diff and agent hooks follow; the plan
lives in `dev/ssot/single-source-of-truth.md`.

## Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

Requirements: Python 3.10+. Per language:

| language | needs | precision |
|---|---|---|
| C / C++ | `compile_commands.json` (`cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON` or `bear -- make`) and a clang resource dir (auto-detected via `clang -print-resource-dir`, override with `--resource-dir`) | exact: sizes, offsets, macros, globals |
| SystemVerilog / Verilog | `verilator` on PATH; sources via `-f list.f`, `--sv-file GLOB`, a lone `*.f` at the root, or every `*.sv`/`*.v` under it | exact: hierarchy, ports with explicit direction, parameters, packed-struct bit layouts |
| Rust | `rust-analyzer` (rustup component) and a `Cargo.toml` at the root | lsp: signatures from hover, struct fields without sizes, no globals |
| Python | `pip install pyright` (needs node) | lsp: as above; dataclass fields from annotations |

The language is picked from the entry file's extension; force it with `--lang`.

## Use

```bash
hx extract src/dma.c:dma_start --depth 3            # callees, 3 levels
hx extract src/hal.c:hal_write32 --include-callers   # who calls this (negative depth)
hx extract include/dma.h:dma_poll --all -o out/g.json
hx extract src/main.c:app_run --exclude 'third_party/*' --type-depth 1 -v
hx extract rtl/top.sv:top -f files.f                 # SystemVerilog: module hierarchy from the top
hx extract rtl/core.sv:top.u_core_b.u_alu --include-callers   # one instance path, parents included
hx extract src/lib.rs:app_run                        # Rust via rust-analyzer
hx extract pkg/main.py:app_run --lsp-timeout 120     # Python via pyright
```

For HDL the nodes are module instances (`sv:rtl/core.sv::top.u_core_a`) carrying
their module's ports, parameters and internal signals; `instance` edges carry the
port connections as written; functions and tasks are nodes of their own; struct
and enum sizes are in bits. LSP languages are labelled `precision: lsp` in every
node: good call graphs and signatures, no memory layout, and calls through
closures or function pointers are invisible to the server.

Output summary:

```
entry       c:src/main.c::app_run
nodes       7   edges 11   types 14   globals 4   unresolved 4
tus         3 total, 3 parsed, 0 cached, 0 failed, 0 compile errors   (0.05s)
output      .hx/graph.json
```

Translation units are cached under `.hx/cache/` by source and header mtimes,
so a re-run after an edit re-parses only what changed.

## View

```bash
hx serve                    # http://127.0.0.1:8765/ on .hx/graph.json, annotations in .hx/annotations.json
hx serve out/g.json --open  # any graph; --no-extract disables the re-extract button
hx export -o view.html      # standalone HTML (graph + annotations + viewer inlined), no server needed
```

The viewer has three panes: the hierarchy tree (callers above, callees below,
unresolved targets grouped by reason), the graph (nodes grouped by file, depth
slider, double-click collapses a subtree, drag pins a node, hover an edge for
the call-site arguments), and the detail pane (signature, parameters with a
clickable in/out chip, struct layouts with offsets, globals, call sites, source
snippet, notes and tags, a *verified* checkbox that pins the body hash and
flags later changes).

Edits go to `annotations.json` through `PATCH /api/annotations` (JSON merge
patch) and survive re-extraction because they are keyed by stable ids. The
server watches `graph.json` and `annotations.json`; when either changes on disk
(for example an agent ran `hx extract`), every open tab reloads via
Server-Sent Events. The **re-extract** button re-runs the last `hx extract`
arguments recorded in `graph.meta.extract_args`.

Keyboard: `/` search · `f` fit · `Esc` clear selection · `Backspace` back.
URL hash carries selection, depth and layout, so links are shareable;
`?theme=dark|light` forces a theme and `?live=0` disables the live connection.

API: `GET /api/graph`, `GET|PUT|PATCH /api/annotations`, `POST /api/extract`,
`GET /api/source?file&line&span`, `GET /api/status`, `GET /events` (SSE).

## What is in graph.json

| key | content |
|---|---|
| `nodes` | functions: id, signature, `params[].dir` (in/out/inout + source of that judgement), `returns`, `globals.reads/writes`, `calls`, `body_hash`, `depth` |
| `types` | structs/unions/enums/typedefs reached from signatures and globals: `size`, `align`, `fields[]` with byte `offset`, `size`, bitfield `bit_offset`/`bit_width`, `underlying_ref` for typedefs |
| `globals` | file-scope and function-local static variables touched, with type refs |
| `edges` | `from`/`to` + `kind` (`call`, `macro`, `fnptr`, `ref`), call-site `loc` and `args` as written |
| `unresolved` | anything reached but not expanded, with a reason: beyond depth, no definition, system header, excluded, function pointer |

Stable id forms: `c:src/dma.c::dma_start`, `c:include/dma.h::struct dma_chan`,
`c:include/dma.h::dma_chan_t`, `c:include/dma.h::anon@L23`,
`c:src/main.c::app_run.ch` (function-local static).

In/out for C is a heuristic (`dir_source: heuristic`): by-value and
pointer-to-const are `in`, other pointers/arrays are `inout`. The annotation
layer (Phase 2) lets you override per parameter.

## Develop

```bash
python -m pytest -q
```

Layout: `hx/model.py` (IR), `hx/ids.py` (stable ids), `hx/traverse.py` (BFS),
`hx/cache.py`, `hx/frontends/clang_fe.py` (libclang), `hx/frontends/verilator_fe.py`
(verilator XML), `hx/frontends/lsp_fe.py` (JSON-RPC client + call hierarchy), `hx/annotations.py`,
`hx/serve/app.py` (FastAPI), `hx/export.py`, `hx/viewer/` (vanilla JS app +
vendored Cytoscape/dagre, no build step), `hx/cli.py`, `tests/fixtures/{c,sv,rust,python}/`
(fixture projects; `tests/test_conformance.py` runs the same invariants over
every frontend whose toolchain is installed). Headless check of the viewer:
`google-chrome --headless=new --screenshot --virtual-time-budget=3000 "http://127.0.0.1:8765/?live=0"`.
