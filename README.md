# hx — function-scoped structure extractor

[![Regression status](https://img.shields.io/github/actions/workflow/status/CansWang/hierX/ci.yml?branch=main&label=regression)](https://github.com/CansWang/hierX/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](#install)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Documentation:** [Start here](docs/index.md) ·
[C/C++ tutorial](docs/tutorials/c-review.md) ·
[Netlist quickstart](docs/tutorials/netlists.md) ·
[Python API](docs/reference/python.md) ·
[CLI reference](docs/reference/cli.md)

Build and preview the full documentation from this checkout with
`python -m pip install -e '.[docs]'` and `mkdocs serve`.

`hx` answers one question quickly: **starting from this function, what does the
code look like?** It walks the call hierarchy to a chosen depth and records,
for every function reached, its signature, parameters tagged in/out, the
resolved types behind them (structs with field offsets, typedef chains,
enums), the globals it touches, and every call edge, including calls hidden
behind macros and calls through function pointers.

The output is a schema-versioned JSON graph (`hx/schema/hx-4.schema.json`). It
is designed to be regenerated after every AI-agent editing session and then
**diffed and viewed** instead of reading the agent's narration. IDs are stable
across regeneration for the same build configuration, so notes you attach later
survive; see [Boundaries](#boundaries) for what does and does not move them.

Status: **0.5.0 — Rust, Xyce, and circuit review hardening** — C/C++ (libclang), SystemVerilog/Verilog (verilator),
Rust (rust-analyzer), Python (pyright) and SPICE-family netlist (native parser for the `spice`, `ngspice` and
`xyce` dialects; ngspice, Xyce and XDM as optional oracles) frontends; browser viewer with editable
annotations, live reload and diff mode; tracked entry points with history,
`hx diff`, a watch loop, an update hook and an MCP server. The plan lives in
`dev/ssot/single-source-of-truth.md`; the netlist dialect coverage in
`dev/ssot/netlist-dialect-matrix.md`.

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

Requires Python 3.10+. The base install includes C/C++ bindings, the viewer
server, MCP support and Pyright with its [packaged Node.js runtime](https://pypi.org/project/pyright/).
Python 3.10 also pulls in `tomli` automatically. The `mcp` extra remains
available for compatibility with existing install commands.

### Optional installations

Choose the tools needed for your languages and development workflow. Run the
Python commands in the activated virtual environment above. The system-package
commands below are Ubuntu/Debian examples; run `sudo apt-get update` first.

| purpose | installation commands |
|---|---|
| Development and the pytest suite | `python -m pip install -e ".[dev]"` |
| Browser automation with Playwright | `python -m pip install -e ".[dev,e2e]"`, then `python -m playwright install --with-deps chromium` |
| C/C++ compiler, standard headers and Clang resource headers | `sudo apt-get install -y clang build-essential` |
| SystemVerilog / Verilog extraction | `sudo apt-get install -y verilator` |
| ngspice, the netlist oracle (`hx netlist check --oracle ngspice`; extraction itself needs no simulator) | `sudo apt-get install -y ngspice` ([download page](https://ngspice.sourceforge.io/download.html)); or `--ngspice PATH` / `HX_TOOL_NGSPICE` |
| Rust extraction, with Rustup installed | `rustup toolchain install stable --profile minimal`, then `rustup component add --toolchain stable rust-analyzer rust-src` |
| Standalone JavaScript tests (`node --test tests/js`) | `sudo apt-get install -y nodejs` |
| Optional Clang LSP profile | `sudo apt-get install -y clangd` |
| Experimental Go profile, with Go installed | `go install golang.org/x/tools/gopls@latest` |

For Rust, install [Rustup](https://rustup.rs/) if needed and load its shell
environment with `. "$HOME/.cargo/env"` so `cargo`, `rustc` and `rust-analyzer`
are on PATH. The [rust-analyzer instructions](https://rust-analyzer.github.io/book/installation.html)
explain the standard-library source requirement. For Go, install the
[Go SDK](https://go.dev/doc/install) first and put `$(go env GOPATH)/bin` on
PATH (or your configured `GOBIN`); see [gopls installation](https://go.dev/gopls/).
The Go profile has no integration tests yet. A cross-compiled C/C++ project
also needs its target compiler/SDK headers as specified by its compilation
database.

The `e2e` extra supplies [Playwright browser automation](https://playwright.dev/python/docs/browsers)
for `tests/test_e2e_viewer.py` (layout on the minimized CVA6 graph and its
fallbacks, selection restore, an SSE round trip observed in the DOM, source
navigation, note deletion through the DOM, wide parameter display); install its
Chromium with `python -m playwright install chromium`. That installation is
separate from Pyright's Node.js runtime. The JavaScript unit tests need a
standalone `node` executable on PATH.

### Netlist integrations

The CLI supports `--oracle ngspice`, `--oracle xyce` and `--oracle xdm`.
Extraction needs none of them. Xyce checks syntax/topology, normalized family
counts and exposed net names; XDM checks the top-level primitive inventory.
XDM translation warnings or omitted U devices are unavailable checks, never
agreement. HSPICE and Spectre syntax remain deferred.

| integration | installation guidance |
|---|---|
| Xyce oracle (`--xyce PATH` or `HX_TOOL_XYCE`; without either, PATH, then `/usr/cad/xyce/parallel/bin/Xyce` and `/usr/local/Xyce/bin/Xyce` are tried) | installer or source build from [Xyce downloads](https://xyce.sandia.gov/downloads/) |
| XDM structural check (`--xdm PATH` or `HX_TOOL_XDM`; without either, PATH, then `~/.local/bin/xdm_bdl`) | `xdm_bdl` bundle from [XDM releases](https://github.com/Xyce/XDM/releases) |
| HSPICE (deferred) | licensed Synopsys installation |
| Spectre (deferred) | licensed Cadence installation |

### Project requirements

Per-language project requirements:

| language | needs | precision |
|---|---|---|
| C / C++ | `compile_commands.json` (`cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON` or `bear -- make`) and a clang resource dir (auto-detected via `clang -print-resource-dir`, override with `--resource-dir`) | exact: sizes, offsets, macros, globals |
| SystemVerilog / Verilog | `verilator` on PATH; sources via `-f list.f`, `--sv-file GLOB`, a lone `*.f` at the root, or every `*.sv`/`*.v` under it | exact: hierarchy, ports with explicit direction, parameters, packed-struct bit layouts |
| Rust | `rust-analyzer` (rustup component) and a `Cargo.toml` at the root | lsp: signatures from hover, struct fields without sizes, no globals |
| Python | Pyright and its Node.js runtime are included in the base install | lsp: as above; dataclass fields from annotations |
| SPICE-family netlists (`.sp .spi .spice .cir .ckt .net .sub .lib .inc`) | nothing: a native parser. `--dialect auto\|spice\|ngspice\|xyce` (sniffed from `.control`/`.if`/`.csparam`), `--deck FILE` when the entry file is an include or library, `--search-path DIR` (repeatable). Simulators are optional oracles for `hx netlist check` only | syntax: hierarchy, device terminals, nets, scoped models and definitions, symbolic parameters (never evaluated) |

The language is picked from the entry file's extension; force it with `--lang`.

Without `--root`, hx resolves the entry file from the run directory and walks
upward from the real source path, stopping at the **first `.github` directory**.
That directory's parent becomes the project root, with `.hx` beside `.github`.
Nested repositories/submodules with their own marker keep their own state; a
`.git` directory/file alone is not a marker. With no `.github` above the source,
`.hx` goes under the run directory. Explicit `--root` overrides discovery;
`--root .` preserves run-directory extraction. Commands without an entry search
upward from the run directory. See [project-root rules](docs/reference/configuration.md#choose-the-project-root).


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
hx extract evals/ota.sp:. --dialect ngspice          # a SPICE deck: subcircuit instances and devices, with the circuit block
hx extract evals/ota.sp:xdut.m_load_1 --include-callers   # one device, its instance path above it
hx extract models/pdk.sp:@nfet_03v3 --deck evals/ota.sp   # a definition-rooted view of a subcircuit (ids reusable across decks)
hx netlist check evals/ota.sp:. --oracle ngspice     # cross-check paths, arity, nets, models and references against the simulator
```

### SystemVerilog on a real project

A real HDL repository needs package ordering, include directories and a
configuration selection, so give `hx` the same argument file the simulator
uses (the CVA6 core, for example, ships one per configuration):

```bash
TARGET_CFG=cv64a6_imafdc_sv39 hx extract core/cva6.sv:cva6 -f core/Flist.cva6 --top cva6 --depth 3
hx extract core/frontend/instr_scan.sv:cva6.i_frontend.gen_instr_scan[0].i_instr_scan --depth 0 -f core/Flist.cva6 --top cva6
```

- `-f LIST` / `-F LIST` are read with Verilator's rules: `+incdir+DIR`, `-D`/`-G`
  defines and parameter overrides, `$VAR`, `${VAR}` and `$(VAR)` from the
  environment, nested `-f` (relative paths resolve against the working
  directory) and `-F` (against the list's own directory). Other Verilator
  options go through `--extra-arg`.
- The entry's file is part of the request: a module or function name must be
  defined in that file; an instance path's file must define the module of some
  cell on the path (its top, an intermediate, or the leaf). A wrong or stale
  path is an error that names the right file, never a silently different graph.
- Generate-array instances use source spelling, `gen_lane[0].u_lane`; Verilator's
  `gen_lane__BRA__0__KET__` is accepted as input and never emitted.
- Recursive discovery (every `*.sv`/`*.v` under the root, or a lone `*.f`) is a
  convenience for small trees only.
- The cache identity is the expanded content of every argument file, the
  Verilator version (`verilator --version`, not the wrapper script's mtime),
  the top module and the extra arguments; switching `TARGET_CFG` or editing a
  nested list misses the cache, repeating a run hits it, and a missing
  executable fails even with a warm cache.
- Verilator warnings that survive `-Wno-lint -Wno-style` (`SELRANGE`,
  `WIDTHCONCAT`, …) are counted apart from errors (`meta.index.warnings`,
  `warnings_by_tag`, a note, and the first twenty under `-v`).

For HDL the nodes are module instances (`sv:rtl/core.sv::top.u_core_a`) carrying
their module's ports, parameters and internal signals; `instance` edges carry the
port connections as written (shorthand `.clk` becomes `.clk(clk)`, wildcard
connections `.clk(.*)`), including instances inside generate blocks; functions
and tasks are nodes of their own; struct and enum sizes are in bits; a module's
`loc` spans `module … endmodule`. LSP languages are labelled `precision: lsp` in
every node: good call graphs and signatures, no memory layout, and calls through
closures or function pointers are invisible to the server.

### Netlists

A SPICE-family deck is read by hx's own parser (`precision: syntax`); no
simulator is needed to extract. The deck is the `module` node, every `X` line
an `instance` node carrying its definition's ports, every primitive element a
`device` node carrying its terminals, and `instance` edges carry the nets as
written. The additive `circuit` block holds what call graphs have no place for
(see [What is in graph.json](#what-is-in-graphjson)).

- **Entries.** `deck.sp:.` is the whole deck; `deck.sp:xdut.m1` an instance or
  device path (case-folded, `#<guard_id>` addresses an occurrence inside an
  `.if` branch); `lib.sp:@opamp` (`@scope/name` for a subcircuit declared
  inside another) a definition-rooted view, extracted on its own or with
  `--deck` for the deck's declarations; `/name` forces the instance reading
  when a name is both. Without `--deck`, a `@name` entry whose line 1 is a
  dot-directive is read as a standalone library (line 1 kept, as under
  `.include`); a prose line 1 is a deck title. A deck whose title line is
  itself a directive gets `title-is-directive`, since ngspice ignores it. The entry's file must hold the deck, define the
  subcircuit, or hold a statement on the path, else the error names the right
  file and suggests near names.
- **Scoped lookup.** Definitions, models and parameters are looked up from the
  innermost subcircuit outward to the deck and its library sections, so a
  local `.model` or `.subckt` shadows a global one (the shadowed outer
  declaration stays in the record with status `shadowed`). Two declarations of one name in one scope are `ambiguous`, never
  last-wins. A model that exists only as bins (`nfet_03v3.0 … .15`) resolves
  to the family with `status: binned`.
- **Conditionals (ngspice).** An occurrence inside `.if/.elseif/.else` carries
  its guard (`attrs.guard`, an id derived from the conditions, never from
  position); a `.model` declared in two exclusive branches is `alternatives`;
  the same name in two compatible branches is `ambiguous`; the same name under
  identical conditions twice is a `guarded-duplicate`. Declaration records
  list every branch's declaration (one file included from both branches
  gives two), and a controlling reference (`F`/`H`/`K`) to a source declared
  in exclusive branches keeps every alternative (`attrs.controls[].targets`,
  one `ref` edge each; overlapping targets are `ambiguous-reference`, a
  missing one a ghost). Nets are canonicalised through each occurrence's own
  enclosing instances, so two guarded `xw` lines that swap nets give their
  nested devices different nets (`terminals[].canonical`, `ports[].net`).
- **Includes and libraries.** `.include` resolves absolute, then against the
  including file's directory, each `--search-path`, then the root; `.lib "f"
  sect` reads only that section (and the sibling sections it pulls, as PDK
  libraries do). Every candidate path tried is recorded in `meta.probes`
  (missing ones included) and every file read in `meta.deps`, so `hx watch`
  and the cache react to an edit, a newly created include and a candidate that
  now shadows the resolved file. A missing include is an error diagnostic;
  extraction continues. Files outside the root keep absolute paths in their ids.
- **Cache.** Each file's raw statements are cached once per dialect, so a PDK
  library parses once across decks. The summary line reads
  `files N total, P parsed, C cached, D diagnostics (E errors)   dialect ngspice (t s)`.
- **Hashes.** `body_hash` is a token hash over the statement (devices) or the
  scope (deck, definitions): comments, case, whitespace, continuation layout,
  expression spacing (`{w * 2}` is `{w*2}`) and unrelated reordering do not
  move it; a condition edit (`.if (pick > 0)` to `(pick > 1)`) moves the hash
  of every scope holding that conditional. Parameters stay symbolic. `hx diff`
  reports rewiring on the line that changed (an instance's own nets, a
  device's own terminals), never on the descendants that inherit it.
- **Diagnostics.** `circuit.diagnostics` carries codes such as
  `missing-include`, `include-cycle`, `duplicate-definition`,
  `missing-definition`, `terminal-count-mismatch`, `unknown-device-family`
  (tokens kept, `attrs.family: "?"`), `missing-model`, `ambiguous-model`,
  `unsupported-directive` (preserved), `unparsed-statement` (text kept),
  `encrypted-content`, `ends-name-mismatch`, `guarded-duplicate`,
  `missing-reference`, `ambiguous-reference`, `title-is-directive`,
  `model-not-visible`, `missing-lib-section`, `lib-section-skipped` (info),
  `recursive-hierarchy`, `hierarchy-too-deep`; counts are
  in `meta.notes`, the first thirty under `-v`. Only an unreadable deck or an
  entry that is not found aborts.
- **`.control` blocks** are kept verbatim in `circuit.control_blocks` and never
  executed; the oracle strips them from every file before handing ngspice the
  rendered include closure on standard input, so an include that writes files
  from a control block has no side effect and a search-path-only include is
  found.
- **Oracle.** `hx netlist check ENTRY --oracle ngspice` compares, for every
  unguarded device, its hierarchical path, terminal count, nets, model and
  controlling references with ngspice's `listing expand`; guarded occurrences
  and the simulator rows they could spell are counted, not compared; a family
  that needs a model (`M`, `Q`, `D`, `W`, …) is always compared on it, so a
  model missing on either side is a `model` mismatch, never a skipped check;
  an instance-path entry restricts both sides to that subtree and a device
  entry both sides to that one device (ngspice only:
  `--oracle xyce|xdm` always check the whole deck and read `--dialect auto` as
  `xyce`, and every report prints `scope` and `dialect` lines saying what was
  compared); a definition-rooted entry with deck context (`lib.inc:@cm --deck deck.sp`, or
  a deck's own `deck.sp:@name`) is compared once per unguarded instance of the
  definition and reports each; a deck ngspice cannot run (symbolic
  parameters), or a definition with no unguarded instance, is "oracle
  unavailable" with the reason quoted, as is a simulator that exits non-zero,
  prints no listing or exceeds `--timeout`. Mismatch kinds: `missing-in-hx`,
  `missing-in-ngspice`, `arity`, `net`, `model`, `ref` and `name-form` (a
  tolerant name match is reported, never silent). Exit 0 agree, 1 mismatch,
  2 tool missing or unavailable. A missing tool is named with its install command:
  `ngspice executable 'ngspice' not found (needed for the ngspice oracle (`hx netlist check --oracle ngspice`)); install it (sudo apt-get install -y ngspice, https://ngspice.sourceforge.io/download.html) or pass --ngspice PATH`.
  In strict mode (`HX_REQUIRE_TOOLS=1`) ngspice is required; vendor tools are
  required per `HX_REQUIRE_VENDOR_TOOLS=xyce,xdm` (or `all`).
- **Dialects.** `spice`, `ngspice` and `xyce` (`dev/ssot/netlist-dialect-matrix.md`
  lists every construct). `--dialect auto` sniffs `spice` or `ngspice` only, so
  select Xyce with `--dialect xyce`. HSPICE and Spectre syntax remain deferred.

Output summary:

```
entry       c:src/main.c::app_run
nodes       7   edges 11   types 14   globals 4   unresolved 4
tus         3 total, 3 parsed, 0 cached, 0 failed, 0 errors, 0 warnings   (0.05s)
output      .hx/graph.json
```

Translation units are cached under `.hx/cache/` by source and header mtimes,
so a re-run after an edit re-parses only what changed.

Default extraction also keeps a stable current graph per entry under `.hx/graphs/`.
CLI extraction, updates, MCP, and viewer re-extraction share the same save mechanism:
before replacing a current graph, its exact bytes are archived in `.hx/history/`.
The first extraction has no history. `.hx/graph.json` remains the latest default
CLI selection and follows later updates of that entry. `-o FILE` writes only FILE.

New graphs include `meta.provenance`: run times and ID, hx version, the entry's
actual Git repository/commit and dirty status, plus SHA-256 fingerprints of
observed inputs, options, and graph content. Snapshots use UTC time, commit prefix,
and run ID in their filenames. Old graphs retain unknown provenance; input
coverage is observed, not a complete account of every compiler/server input.
See [storage](docs/reference/configuration.md#generated-project-state) and
[provenance](docs/reference/graph.md#extraction-provenance).

## View

```bash
hx serve                    # http://127.0.0.1:8765/ on .hx/graph.json, annotations in .hx/annotations.json
hx serve out/g.json --open  # any graph; --no-extract disables the re-extract button
hx export -o view.html      # standalone HTML (graph + annotations + viewer inlined), no server needed
```

Without a graph argument, `serve` and `export` choose an existing run-directory
`.hx` first; otherwise they use `.hx` at the first `.github` found upward from the
run directory. An empty local `.hx` or missing state at that first marked root is
an error, with no fallback to an outer repository. Within the selected state,
`graph.json` is preferred, then the first regular `graphs/*.json` in filename
order, excluding the reserved `annotations.json` file. Pass a graph path to
bypass discovery. `serve --root` only overrides source lookup. Existing `.hx`
directories are not moved or merged automatically.

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

Graphs under the same `.hx`, including saved historical snapshots, share
`.hx/annotations.json` with MCP. Standalone graphs outside `.hx` use an adjacent
annotation file; `serve` and `export` accept `--annotations FILE` to override it.
Source lookup overrides do not change annotation selection.

When the shared file is absent, viewer/MCP startup copies one unambiguous legacy
sidecar from the graph/history directories, preserving its original bytes and
file. Export can read that same legacy file without importing it. Multiple legacy
files require explicit selection; no files are merged automatically. Use
`--annotations FILE` for serve/export, or copy your chosen file to
`.hx/annotations.json` before starting MCP. An existing shared file takes precedence.

Keyboard: `/` search · `f` fit · `Esc` clear selection · `Backspace` back.
URL hash carries selection, depth and layout, so links are shareable;
`?theme=dark|light` forces a theme and `?live=0` disables the live connection.

API: `GET /api/graph`, `GET /api/graphs`, `GET /api/history`, `POST /api/snapshot`,
`GET /api/diff?since&format`, `GET|PUT|PATCH /api/annotations`, `POST /api/extract`,
`GET /api/source?file&line&span`, `GET /api/status`, `GET /events` (SSE); every
route and status code is in [the HTTP reference](docs/reference/http.md).

**Hiding modules.** Every function or module row in the hierarchy has an eye
button (also the "hide module" button in the detail pane, or `h` on the
selection). Hiding a module removes it, every edge into or out of it, and
everything that is only reachable through it: its submodules, callees and
unresolved ghosts. A function another visible module still calls stays. Hidden
rows stay in the tree, dimmed, under a `hidden (n) · show all` section, and
the state is kept in `annotations.json` (`view.hidden`), so it survives
reloads and re-extraction and carries into exported pages.

## Track, diff, watch (the agent loop)

```bash
hx track src/main.c:app_run --depth 3        # remember an entry point in .hx/config.toml
hx track rtl/top.sv:top -f files.f
hx track evals/ota.sp:. --dialect ngspice --search-path models   # netlist options are tracked too
hx update                                     # re-extract all tracked entries, snapshot the old graphs, print what changed
hx update --quiet                             # one line per entry (used by the hook)
hx diff --entry src/main.c:app_run            # current graph vs the last snapshot (or --since <ts>)
hx diff old.json new.json --format json       # any two graphs
hx watch                                      # poll sources; update after each quiet period
hx hook install --settings-dir path/to/settings # install a hook that runs `hx update --quiet --hook`
hx mcp --print-config                         # MCP server configuration snippet
```

`hx update` writes one graph per entry under `.hx/graphs/`, keeps the previous
graphs under `.hx/history/<entry>/` (pruned to 20), and writes `.hx/last-diff.md`:
added/removed functions, signature and parameter changes, body changes with line
deltas, struct field and offset shifts, new or removed call edges, changed call
arguments, and newly unresolved targets. About twenty lines, meant to be read
instead of the agent's narration. Line-number drift, whitespace-only edits and
system typedef noise do not register as change.

`hx serve` lists every tracked graph in a picker, offers a **baseline** button
that snapshots the current graph, and a **diff** selector that colors the graph
(green new, amber changed, red removed) with a changes list and per-symbol
change details. Links carry `#graph=…&diff=…`.

`hx mcp` exposes `list_graphs`, `search`, `get_function`, `callees`, `callers`,
`get_type`, `diff_since`, `extract`, `annotate`, and for netlist graphs `get_net`
and `netlist_uses`, as compact text tools, so an
agent can ask "who calls this, with what arguments" or "what changed since the
baseline" without re-reading files. `extract` takes the tracked entry's options
(depth, callers, language, dialect, deck, search paths) for anything the agent
leaves out, an explicit value (including `depth: 3` or `include_callers: false`)
overrides, and `track: true` persists the merged table.

## What is in graph.json

| key | content |
|---|---|
| `nodes` | functions: id, signature, `params[].dir` (in/out/inout + source of that judgement), `returns`, `globals.reads/writes`, `calls`, `body_hash`, `depth` |
| `types` | structs/unions/enums/typedefs reached from signatures and globals: `size`, `align`, `fields[]` with byte `offset`, `size`, bitfield `bit_offset`/`bit_width`, `underlying_ref` for typedefs |
| `globals` | file-scope and function-local static variables touched, with type refs |
| `edges` | `from`/`to` + `kind` (`call`, `macro`, `fnptr`, `ref`, `instance`), call-site `loc` and `args` as written |
| `unresolved` | anything reached but not expanded, with a reason: beyond depth, no definition, system header, excluded, function pointer |
| `circuit` | netlist graphs only: `dialect`, `deck`, `root`, `files[]` (role, section, resolver), `definitions{}` / `models{}` / `params{}` (uniform records with `status` found\|alternatives\|ambiguous\|binned\|shadowed\|missing and one declaration per guard), `nets{}` (kind, bindings, canonical), `terminals{}` (`net` in the device's scope, `canonical` the outermost net through the enclosing bindings) and `ports{}` (`outer` as written in the parent's scope, `net` canonical) keyed by graph nodes only; a definition's `instances` and a model's `used_by` may name unresolved ghost ids (an ambiguous or missing instance keeps its candidates, status `ambiguous` or `missing`); `directives[]`, `control_blocks[]`, `probes[]`, `diagnostics[]` |

Stable id forms: `c:src/dma.c::dma_start`, `c:include/dma.h::struct dma_chan`,
`c:include/dma.h::dma_chan_t`, `c:include/dma.h::union dma_chan.stat` (anonymous
member type, named after the member that holds it), `c:src/main.c::app_run.ch`
(function-local static), `cpp:src/bus.cpp::hw::Bus::write(const Reg &)` (C++
functions always carry their parameter types, so overloads never rename each
other). SystemVerilog: package types keep their name
(`sv:rtl/pkg.sv::struct dma_pkg::cfg_t`); a type declared inside a module is
identified by its layout, `sv:rtl/fp.sv::struct fp.fp_t@3f9a1c2e`, so the
32-bit and 64-bit specializations of one parameterized module are two types
and a new specialization never renames an existing one; anonymous inline types
are named by their first declaring context, `struct top.cfg_i@…`. Netlists:
occurrence ids carry the deck, `sp:evals/ota.sp::(deck) ota.sp`,
`sp:evals/ota.sp::xdut`, `sp:evals/ota.sp::xdut.m1` (two decks sharing a
library are two id sets); a definition-rooted view is `sp:lib/pdk.sp::@nfet`
with children `…::@nfet.m0`, reusable across decks; a guarded occurrence adds
`#<guard_id>`; segments are case-folded, the spelling stays in `name`.

Values: an integer below 2^53 is a JSON number; anything wider is a lossless
string in canonical hex (`17270'h1000…` with its width, `0x…` without), x/z
literals keep their bit pattern. The differ compares values numerically, so a
decimal and a hex rendering of one value never register as a change. The
schema is `hx/4`; `hx/1`, `hx/2` and `hx/3` files are read and upgraded in memory, and
`hx migrate` re-extracts a project's tracked entries once and carries
annotations over (see Boundaries).

Call-site arguments and signatures are read with a literal-aware lexer:
commas, brackets or `>` inside a string never split an argument, and the
spaces inside a literal are kept (`"   "` stays three spaces). A call that a
macro expands to carries the macro's own arguments, unless the macro produced
the callee's name (`FUNC(x)(a, b)`), in which case it carries `a, b`.

`body_hash` is a token hash: whitespace between tokens, blank lines and comments
do not change it; string and character literals (verbatim), operator adjacency
(`a--b` vs `a - -b`), Python indentation (relative to the function's first
line) and everything else do. SystemVerilog modules hash their
`module … endmodule` source, so procedural logic counts and a comment above an
instance does not.

In/out for C is a heuristic (`dir_source: heuristic`): by-value and
pointer-to-const are `in`, other pointers/arrays are `inout`. The annotation
layer (Phase 2) lets you override per parameter.

## Boundaries

What the tool promises, and where the promise stops:

- **IDs and build variants.** A function compiled in several translation units
  under different macros (an inline helper in a header) has one graph entry: the
  variant from the TU that defines it, else the first TU in path order. The
  choice is deterministic across cold, partial and warm caches, and
  `meta.notes` says "compiled differently in N build variants". Switching
  `compile_commands.json` (another target, another config) is a different build
  and may legitimately change ids and bodies.
- **C identity.** A `static` function or variable, and every struct, union,
  enum or typedef, is identified by its defining file as well as its name, so
  two `static get_category` in `libavcodec/options.c` and
  `libavformat/options.c` are two functions (libclang alone gives them one
  symbol). A type local to a function carries the function (`struct f::local`).
  Forward declarations, definitions and every file that names a tag inside one
  translation unit are linked, so `struct x;` in several headers and the
  definition elsewhere are one type, and a typedef redeclared in two headers is
  one typedef; nothing is linked by layout alone, and two declarations no
  translation unit ever ties together stay two identities. A type that
  different translation units see with different layouts or different field
  targets gets one id per variant (`struct cfg@<8hex>`), a type only
  forward-declared where the definition is never seen stays `incomplete`, and
  a forward declaration shared by two different definitions is kept apart from
  both; `meta.notes` reports each case, and the rare pair of distinct types
  that would still share an id (the same tag in two blocks of one function)
  keeps both under a `#hash`. Paths are resolved through symlinks, so a
  build's `src -> ../source` link does not change ids.
- **Python identity.** Nested functions carry their enclosing function
  (`outer.helper`); module-level code that calls into the project is a `module`
  node spanning the file, hashed over the whole file; a call into an
  overloaded stub declaration (typeshed `getattr`, `str.join`, your own `.pyi`)
  is one edge to one target whose `unresolved` record says how many overloads
  it stands for.
- **C++.** Overloads are distinguished by the spelled parameter type list in the
  id; changing a parameter's type therefore reads as a removed + added function.
  Template instantiations are not expanded; the primary template is recorded.
  Residual collisions (identical spelled signatures) get a `#hash` suffix.
- **Body hashes** see tokens, not semantics: a renamed local variable is a
  change, a reformat or comment is not. For Rust and Python the body is the text
  of the function's range as the language server reports it.
- **Language-server precision** (`precision: lsp`): no sizes or offsets, call
  edges exactly as the server reports them, no globals, and extraction restarts
  the server per run (seconds, not milliseconds).
- **Watching** polls mtimes (default every 2 s) under the project root, skipping
  `build`, `target`, `.venv` and similar, but still watching a
  `compile_commands.json`, `Cargo.toml` or `pyrightconfig.json` placed inside
  them. There is no inotify backend.
- **Persistence.** Graphs, config, `last-diff.md` and annotation edits use atomic
  replacement; snapshots and legacy-note imports use exclusive atomic creation.
  Annotation read-modify-write takes a cross-process file lock, so `hx serve`,
  `hx mcp` and the CLI can share one
  `annotations.json`; two servers on different machines sharing a network
  drive are not supported.
- **Schema.** Readers must ignore unknown fields; `hx/4.x` only adds fields.
  `hx/1`, `hx/2` and `hx/3` files are upgraded in memory by every reader (relabelling
  and a report only): ids that the new rules derive differently (nested Python
  functions, module callers, C statics and types keyed by file, symlinked
  paths, collapsed overload targets, Rust trait implementations, SystemVerilog layout-identified types) are
  mapped only by `hx migrate`, which re-extracts every tracked entry into a
  staging area, commits only when all succeed, then rewrites `annotations.json`
  once (backup `annotations.json.bak-hx1`, `.bak-hx2` or `.bak-hx3`, never overwritten).
  Nodes map by file, kind, name and line, with signature/body evidence for Rust
  line drift; ghost targets by call site with the
  overload-family evidence of the new graph; types by base id and users.
  Ambiguous or unmatched keys are listed, never guessed; a `verified` mark on
  a node that became a module node is dropped because its hash now covers the
  file. History snapshots keep their old ids, so the first `hx update` after a
  migration shows a one-time removed/added churn. Newer majors are refused.
- **Layout-identified types.** Editing a module-scoped struct changes its id;
  the diff pairs the old and new id through their users and reports one changed
  type, and notes attached to the old id are listed as orphaned by `hx migrate`.
- **Netlists.** Ids are case-folded for the supported SPICE-family dialects;
  HSPICE and Spectre are deferred. Parameters and
  expressions are kept as written and never evaluated, so model bins are
  resolved to the family rather than a W/L bin. Each optional oracle reports
  its checked dimensions and unavailable constructs. Occurrences inside `.if` branches are
  distinguished by `attrs.guard` and the `#<guard_id>` suffix only. Files
  outside the project root keep absolute, machine-specific paths in their ids.
  `.control` blocks are stored, never executed. Unknown device letters and
  directives are preserved with a diagnostic. Xyce supports named `Y` devices,
  digital `U` selectors, `.func`, `.measure` and `.data` structurally; XSPICE `A`
  devices and `.alter` remain outside current coverage.
- **Viewer layout.** In hierarchy graphs a file's functions and tasks are
  grouped apart from its module instances (`file · functions`): a group that
  mixes both, joined by a call edge, makes dagre's ranker throw (CVA6 at depth
  3, with dagre 0.8.5 and 1.1.4 alike). Should dagre still fail, the viewer
  retries with the longest-path ranker, then without groups, then breadth-first,
  says so in the banner, and always finishes initialization. Edges do not avoid
  nodes.

## Develop

```bash
python -m pytest -q                      # skips tests whose toolchain is missing
HX_REQUIRE_TOOLS=1 python -m pytest -q   # missing required toolchains fail; vendor checks are separately opt-in
node --test tests/js                     # viewer merge-patch and circuit-query unit tests (also run from pytest)
pip install -e ".[e2e]" && python -m playwright install chromium   # browser workflow tests (tests/test_e2e_viewer.py)
```

`.github/workflows/ci.yml` installs the required toolchains (verilator, clang,
ngspice, rust-analyzer, node) on Python 3.10 and 3.12, checks a clean base
`python -m pip install .` before adding developer dependencies, and verifies
MCP imports, Pyright and dependency consistency. It then installs `.[dev,e2e]`
and Chromium and runs the suite with `HX_REQUIRE_TOOLS=1`. Optional vendor checks
remain skippable unless named in `HX_REQUIRE_VENDOR_TOOLS`.

Layout: `hx/model.py` (IR), `hx/ids.py` (stable ids, lexer), `hx/values.py` (wide
values), `hx/graphio.py` (the one graph reader; in-memory schema upgrades),
`hx/paths.py` (project-root and graph discovery), `hx/provenance.py`
(`meta.provenance`), `hx/traverse.py` (BFS), `hx/cache.py`, `hx/fsutil.py` (atomic
writes, file lock), `hx/frontends/clang_fe.py` (libclang), `hx/frontends/verilator_fe.py`
(verilator XML), `hx/frontends/lsp_fe.py` (JSON-RPC client + call hierarchy) with
`hx/rustsyntax.py` (Rust token splitting), `hx/frontends/spice_fe.py` over
`hx/netlist/` (profiles with the pinned Xyce inventory `xyce_devices.json`, lexer,
parser, grammar, index, resolver, hashing, ngspice oracle, `xyce.py` Xyce/XDM
checks, `query.py` saved-graph net/uses queries) with `hx/tools.py` (optional-tool
registry), `dev/scripts/netlist_coverage.py` (apragma and sky130 coverage run) and
`dev/scripts/hardening_coverage.py` (pinned Codex/Xyce/XDM acceptance runner), `hx/diff.py`,
`hx/project.py` (config, snapshots, update, watch, hook, migrate), `hx/mcp_server.py`, `hx/annotations.py`,
`hx/serve/app.py` (FastAPI), `hx/export.py`, `hx/viewer/` (vanilla JS `app.js`,
`circuit.js` net queries shared with the Node tests, `patch.js`, vendored
Cytoscape/dagre, no build step), `hx/cli.py`, `hx/schema/hx-{1,2,3,4}.schema.json`,
`tests/fixtures/{c,c_macros,c_scoped,c_variants,cpp,cpp_rec,sv,sv_adv,rust,rust_hardening,python,spice,xyce,legacy,viewer}/`
(fixture projects; `tests/test_conformance.py` runs the same invariants over
every frontend whose toolchain is installed). Headless check of the viewer:
`google-chrome --headless=new --screenshot --virtual-time-budget=3000 "http://127.0.0.1:8765/?live=0"`.

## Rust and circuit review in 0.5.0

Rust trait-method IDs include self type and trait arguments, for example
`rs:src/lib.rs::<Item as Convert<String>>::convert`. Qualified entry names keep
`::`; ambiguous short names list candidates. Rust source handling covers nested
comments, closures, raw literals, lifetimes and turbofish calls. Existing Rust
graphs require `hx migrate` for hx/4 identities; history remains immutable.

```bash
hx extract design.cir:. --dialect xyce --all
hx netlist check design.cir:. --oracle xyce
hx netlist check design.cir:. --oracle xdm
hx netlist net out --graph .hx/graph.json --json
hx netlist uses /amp --kind definition --graph .hx/graph.json
```

Net queries are read-only and bounded to the saved graph. MCP exposes `get_net`
and `netlist_uses`. The viewer adds Nets/Definitions/Models navigation, net
highlighting in the hierarchy, and Circuit changes with before/after declaration
records. Static exports support the same connectivity navigation.

The explicit `dev/scripts/hardening_coverage.py` runner uses a pinned Codex
workspace and installed Xyce/XDM tools, writes replayable acceptance artifacts,
and exits nonzero on failed stages. See the Rust guide and netlist tutorial.

## License

This project is licensed under the [MIT License](LICENSE).
