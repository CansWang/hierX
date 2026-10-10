# hx — Single Source of Truth (development strategy)

This file is the bookkeeping record for how `hx` is planned, why, and where it
stands. Update the **Status log** at the bottom whenever a phase, decision or
scope changes. The code is the truth for *what exists*; this file is the truth
for *what is intended*.

## TLDR
- **Problem**: AI agents flood the developer with text. The developer wants a compact, always-current, *structural* view of the code the agents touch, for software and hardware codebases alike.
- **Tool shape**: `hx extract <file>:<symbol>` → `graph.json` (functions, params with in/out, types, structs, call edges, per depth) → `hx serve` (browser UI, interactive, annotatable, live-reload) → `hx diff` (what changed between two extractions, in ~20 lines).
- **Two files, not one**: machine-generated `graph.json` is regenerated freely; human-owned `annotations.json` (notes, tags, in/out overrides, "verified" marks) survives regeneration via stable symbol IDs.
- **One IR, four frontends**: language-neutral intermediate representation; frontends for C/C++ (libclang), SystemVerilog (verilator XML), Rust + Python (generic LSP client). C/C++ first.
- **Decisions made**: metadata format = JSON (schema-versioned; SQLite only if repo-scale indexing is later needed). Tool = Python package. Viewer = browser app bundled into one HTML with vendored libraries (Cytoscape.js + dagre), served by FastAPI. Static structure only; runtime capture reserved for a later phase.

## Glossary
- **IR** — intermediate representation, the language-neutral data model in `hx/model.py`.
- **Call graph** — who-calls-whom.
- **libclang** — Clang's C API for parsing C/C++ with full type info. Used through the pip `libclang` wheel plus the system clang resource dir.
- **compile_commands.json** — per-file compiler flags, emitted by CMake (`CMAKE_EXPORT_COMPILE_COMMANDS=ON`) or Bear.
- **USR** — Unified Symbol Resolution, libclang's cross-file identity string for a symbol. Internal only; mapped to stable IDs.
- **TU** — translation unit, one `.c`/`.cpp` file plus its includes.
- **LSP** — Language Server Protocol, the editor-agnostic "go to definition / call hierarchy" API.
- **MCP** — Model Context Protocol, how agents call external tools.
- **SSE** — Server-Sent Events, one-way push from server to browser.
- **BFS** — breadth-first search.

## Context
- Repo `~/hx` started empty on 2026-10-09; tool working name `hx` matches the repo.
- Dev machine: Python 3.12, Node 20, clang 18 (resource dir `/usr/lib/llvm-18/lib/clang/18`), verilator 5.02 (`--xml-only` dumps elaborated module hierarchy with ports/types), graphviz, sqlite3, Google Chrome (headless screenshots for viewer checks). Not installed: clangd, tree-sitter, rust-analyzer, cargo, pyright.
- User choices: languages C/C++, SystemVerilog/Verilog, Python, Rust; build-aware exact extraction; local server + static export; static only for now.
- Motive to keep central: after an agent session the human should read a **short structural diff + an updated graph**, not agent output. Agents should be able to **query** the graph instead of re-reading files.

## Principles
1. **Never drop silently.** Anything reached but not expanded goes into `unresolved[]` with a reason (beyond depth, no definition, system header, excluded, function pointer, truncated).
2. **IDs are a contract.** `<lang>:<relpath>::<qualname>` forms are stable across regeneration; overload hashes are added only on collision. Annotations key on them.
3. **Exactness is labelled.** Every node carries `precision` (`exact` | `lsp` | `syntax`); every param carries `dir_source` (`explicit` | `heuristic` | `user`). The viewer never pretends.
4. **Regeneration is cheap.** Per-TU cache keyed by source+header mtimes; a re-run after an agent edit re-parses only what changed.
5. **Frontends emit IR, nothing else.** `hx/traverse.py` never looks inside a frontend key.
6. **Human-owned data lives apart from generated data.** `graph.json` vs `annotations.json`.

## Phases (high level)
1. **Core + C/C++** — IR, stable IDs, BFS traversal, CLI, libclang frontend, JSON output, fixture tests. **Done 2026-10-09.**
2. **Viewer + Serve** — single-file browser UI (tree / graph / detail panes), FastAPI server persisting annotations, SSE live-reload, static HTML export. **Done 2026-10-09.**
3. **More frontends** — SystemVerilog via verilator XML; generic LSP frontend driving rust-analyzer and pyright; shared conformance fixtures. **Done 2026-10-09.**
4. **Diff + agent integration** — `hx diff` (Markdown + JSON), post-edit hook that re-extracts configured entries, MCP server so agents query the graph. **Done 2026-10-09.**
5. **Hardening (4.5)** — the eight defects from the external review, tautological tests, reproducible toolchain coverage, documented boundaries. **Done 2026-10-10.**
6. **Real-project hardening (4.6)** — the eleven findings from the CVA6 review (wide constants, SV cache identity, specialized type identity, generated instances, viewer layout failure, anonymous SV ids, source ranges, warnings, entry validation, generate-array spelling, version) plus schema `hx/2` with migration. **Done 2026-10-10.**
7. **Runtime (reserved, not now)** — IR already carries an empty `runtime` slot; instrumentation strategies noted only.

---

## Phase 1 — Core + C/C++ frontend (done)

### Layout
```
hx/
  pyproject.toml              # package "hx", console script "hx"; deps: libclang (+ fastapi/uvicorn from Phase 2)
  hx/
    cli.py                    # hx extract | serve | export | diff | mcp
    api.py                    # extract(...) -> Graph, used by CLI, server and tests
    model.py                  # IR dataclasses + schema version "hx/1"; JSON round-trip
    ids.py                    # stable ID construction + whitespace-insensitive body hashing
    traverse.py               # BFS over a Frontend, depth limit, cycle-safe, exclusion filters, callers
    cache.py                  # per-TU on-disk cache under .hx/cache/ keyed by (path, args) + dep mtimes
    frontends/
      base.py                 # Frontend protocol: locate_entry, function, declaration, type, global_var, callers, stable_id
      clang_fe.py             # libclang implementation (parallel workers, merged USR index)
  tests/
    fixtures/c/               # firmware-style C project; conftest generates compile_commands.json in a temp copy
    test_ids.py  test_traverse.py (fake frontend)  test_clang_fe.py (real libclang)  test_cli.py
```

### IR — `graph.json`, schema `hx/1`
- Top level: `schema`, `generated`, `root`, `lang`, `entry`, `meta`, `nodes{}`, `types{}`, `globals{}`, `edges[]`, `unresolved[]`.
- **Node**: `id`, `kind`, `name`, `qualname`, `lang`, `loc{file,line,end_line,col}`, `signature`, `storage`, `depth` (negative = caller side), `body_hash`, `precision`, `returns{type,type_ref}`, `params[]{name,type,type_ref,dir,dir_source}`, `globals{reads[],writes[]}`, `calls[]`, `runtime: null`.
- **Type**: `id`, `kind` (`struct|union|class|enum|typedef|…`), `name`, `loc`, `size`, `align`, `fields[]{name,type,type_ref,offset,size,bit_offset,bit_width}`, `enumerators[]`, `underlying`, `underlying_ref`, `anonymous`, `system`, `used_by[]`.
- **GlobalVar**: `id`, `name`, `type`, `type_ref`, `loc`, `storage`, `scope` (`file|function-static|member`).
- **Edge**: `from`, `to` (null for function-pointer calls), `kind` (`call|macro|fnptr|ref|instance`), `loc`, `args[]` (as written), `name`, `macro`, `ptr_type`.
- **Unresolved**: `name`, `from`, `reason`, `loc`, `id`.

### Stable IDs
- Functions `c:src/dma.c::dma_start`; C++ overloads `cpp:src/bus.cpp::Bus::write#a1b2c3d4` (hash only on collision).
- Types `c:include/dma.h::struct dma_chan`, typedefs `c:include/dma.h::dma_chan_t`, anonymous `c:include/dma.h::anon@L23`.
- Globals `c:src/dma.c::g_dma_active`; function-local statics `c:src/main.c::app_run.ch`.
- Files outside the root keep their absolute path (system headers).

### Traversal rules
- BFS from entry; `--depth N` (default 3) or `--all`; cycles safe; min depth wins; already-expanded callees get an edge without a depth check (recursion is not "beyond depth").
- `--include-callers` walks the reverse graph with negative depth; callers' other callees are not expanded.
- System headers excluded by default (`--include-system`); `--exclude GLOB` repeatable; `--max-nodes` cap; `--type-depth` (default 2) limits nested struct expansion while typedef aliases are free.

### libclang frontend facts
- Args from compile_commands are sanitized (compiler, `-o`, dep flags, gcc-only flags dropped; include paths absolutized). Cross compilers (`arm-none-eabi-gcc`) get `--target` + their own system include dirs. `-resource-dir` is injected from `clang -print-resource-dir` because the pip wheel ships no headers.
- Param direction heuristic: by-value → `in`; pointer/ref/array to const → `in` (array qualifier is on the array type in libclang); otherwise `inout`. `dir_source: heuristic`.
- Calls inside macro expansions are detected via `MACRO_INSTANTIATION` spans and get `kind: macro` with the macro's spelled args. Function pointers → `kind: fnptr`, `to: null`. Address-taken functions → `kind: ref` and are expanded like callees.
- Global reads/writes: writes = assignment LHS, `++/--`, compound assignment, address taken. Operator kinds come from libclang's C API (`clang_getCursorBinaryOperatorKind`, LLVM ≥ 17) via ctypes so macro-expanded operators are exact; source-slice fallback otherwise.
- Types from system headers are recorded as stubs (no fields) unless `--include-system`.

### Phase 1 verification
- 30 pytest cases (fixture layout checked against a gcc-compiled `offsetof` probe).
- Smoke: cJSON (1 TU, 0.14 s); libuv (35 TUs, 0.8 s cold with parallel workers, 0.15 s cached).

---

## Phase 2 — Viewer + Serve
- **TLDR**: one `viewer.html` (vanilla ES modules + vendored Cytoscape.js/dagre, no build step) served by FastAPI; edits persist to `annotations.json`; SSE live-reload when the graph file changes or a re-extract finishes; `hx export` emits a standalone HTML with data inlined.
- **Layout**: left = hierarchy tree (entry → callees by depth, collapsible, search, callers group); center = graph (optional compound nodes grouped by file, dagre layout LR/TB, depth slider, double-click collapses a subtree, hover edge shows call-site args); right = detail (signature, params table with editable `dir` chip, click type → nested struct/field tree with offsets, source snippet, notes/tags, "verified" checkbox that pins the body hash and flags later changes).
- URL hash holds selection/layout so views are linkable. Unresolved calls render as dashed ghost nodes.
- **API**: `GET /api/graph`, `GET|PUT|PATCH /api/annotations` (PATCH = JSON merge patch, `null` deletes), `POST /api/extract` (re-run with the args stored in `graph.meta`), `GET /api/source?file&line&span` (root-confined), `GET /events` (SSE: `graph`, `annotations`, `extract-start`, `extract-error`, `ping`).
- **annotations.json** schema `hx-ann/1`: `nodes{id:{note, tags[], verified_body_hash, collapsed, params{name:{dir,note}}}}`, `types{id:{note, fields{name:{note}}}}`, `view{hidden[], pinned_positions{}}`. One file per project (`.hx/annotations.json`), shared across entry points.
- **Export** mode has no server: edits stay in memory and a "download annotations" button yields the file.

## Phase 3 — More frontends (done)
- **TLDR**: two new frontend plugins against the same IR, plus a conformance fixture per language asserting identical invariants.
- **As built**: `hx/frontends/verilator_fe.py` and `hx/frontends/lsp_fe.py`; `hx.api.detect_lang` picks the frontend by extension (`--lang` overrides); new CLI flags `--sv-file`, `-f/--filelist`, `--top`, `--verilator`, `--lsp-cmd`, `--lsp-timeout`. IR gained `Node.attrs` (frontend extras: SV module/specialization/parameters/signals, Rust module path) and `DeclRecord.reason` (frontend wording for "not expanded").
- **SV facts**: Verilator lowers enum/struct-typed vars to base vectors in XML; the declared `vartype` name is used to recover the typedef'd enum/struct. Parameter specializations (`core__W10`) collapse onto `origName` for ids; `attrs.specialization` keeps the real name. Packed struct member LSBs are computed from member widths (first member = MSB). Routine call args and port connections are read from source at the XML `loc`. One verilator run per extraction, cached by all files Verilator read.
- **LSP facts**: keys are `<uri>#<line>:<char>`; everything resolves lazily. Readiness = `experimental/serverStatus.quiescent` (rust-analyzer) or no `$/progress` for 0.6 s. Non-function callees (struct/class constructors, enum variants) are reported as unresolved "not a function"; symbols outside the root as "outside project root (library)". `typeDefinition` results must name a type that appears in the spelled parameter type (guards rust-analyzer jumping through `fn` aliases). Python field types come from the source annotation, not pyright's narrowed hover. Rust `dir` = `&mut` → inout else in (heuristic); Python all `in` (explicit).
- **SystemVerilog/Verilog** (`verilator_fe.py`): `verilator --xml-only --xml-output <out> -Wno-fatal <files> [-f list.f] [--top-module X]`; `<module>` → node kind `module`, `<instance>` → `instance` node + `instance` edge, `<var dir=…>` → params with `dir_source: explicit`, `<typetable>` struct/packed-array dtypes → types with bit ranges, functions/tasks → function nodes. Entry forms: `rtl/top.sv:top` (module) or `top.u_core.alu` (instance path).
- **Generic LSP** (`lsp_fe.py`): minimal JSON-RPC-over-stdio client; `prepareCallHierarchy` + `callHierarchy/outgoingCalls|incomingCalls`, `hover` (signature text), `typeDefinition` + `documentSymbol` (struct fields). Nodes marked `precision: lsp` (no sizes/offsets). Rust: rust-analyzer (prereq: rustup). Python: pyright-langserver or jedi-language-server; decide at phase start. Rust `dir`: `&T` → in, `&mut T` → inout, owned → in. Python: all `in` + return.

## Phase 4 — Diff + agent integration (done)
- **TLDR**: the thing the human actually reads after an agent session is `hx diff` output, ~20 lines.
- **As built**: `hx/diff.py` (`diff_graphs` → `hx-diff/1` JSON, `render_markdown`), `hx/project.py` (`.hx/config.toml` entries + watch settings, `.hx/graphs/<slug>.json`, `.hx/history/<slug>/<generated>.json` pruned to 20, `.hx/last-diff.md`, `update()`, polling `watch()`, `install_hook()`), `hx/mcp_server.py` (mcp 2.x `MCPServer`, stdio). CLI: `hx track|update|watch|diff|hook|mcp`. Server: `/api/graphs`, `?name=` on graph-scoped routes, `/api/history`, `/api/diff?since=`, `POST /api/snapshot`; re-extract snapshots the previous graph first. Viewer: graph picker, baseline button, diff selector, green/amber/red classes with text badges, changes list, per-symbol change block, removed functions drawn as red ghosts.
- **Diff identity rules**: nodes/types/globals by stable id; params and fields by name (added/removed/type/dir/offset/size/bits + reordered); edges by (from, to-or-fnptr-name, kind, macro) as multisets, so line drift never registers; equal-count edges with different args → `args_changed`. Anonymous C types are now named by parent and member (`union dma_chan.stat`, `struct dma_chan.(anon#7)`) precisely so a line inserted above them does not churn the diff. System typedefs are summarized, not listed, in Markdown.
- **Hook**: `hx hook install` merges a `Stop` hook (`hx update --quiet --hook`, 300 s timeout) into `<root>/.claude/settings.json`; `--event PostToolUse` matches `Edit|Write|MultiEdit|NotebookEdit`. Hook mode swallows stdin and never exits non-zero so it cannot block the agent.
- `hx diff old.json new.json --format md|json`: added/removed nodes; signature changes (param added/removed/type/dir); struct field changes incl. offset shifts; new/removed edges; body changed (body_hash + LOC delta). JSON form drives viewer "diff mode".
- `.hx/config.toml`: list of entry points to track. `hx watch` re-extracts them on file change (debounced), writes `.hx/last-diff.md`, pushes SSE reload. Wire as a Claude Code `Stop` / `PostToolUse(Edit|Write)` hook.
- `hx mcp`: MCP server exposing `get_function`, `callees(id, depth)`, `callers`, `get_type`, `search`, `diff_since(ts)`.

## Phase 4.5 — Hardening (done)
- **TLDR**: an external review of Phase 4 listed eight defects, three tautological tests and overstated docs. Every finding reproduced; all are fixed with regression tests. Terms: tautology = an assertion that cannot fail; merge patch = RFC 7396 JSON update where `null` deletes; lexer = token splitter.
- **Verdict table** (finding → root cause → fix):
  - H1 body hash collapsed all whitespace (literals, Python indent) → `ids.tokenize(text, lang)`: two modes (C-family, Python); literals verbatim, comments dropped, operators by maximal munch, Python indentation relative to the first line. Also found: pyright's call-hierarchy `range` is only the NAME, so Python bodies were never hashed at all → `LspFrontend._full_range` (documentSymbol, then indentation/brace scan).
  - H2 SV module hash = repr(ports, signals, instances with `loc`) → hash of the `module … endmodule` source slice (routines likewise), XML-without-locations fallback.
  - H3 index depended on cache state; `include_system` absent from the key → summaries merged in TU-path order, the defining TU wins, `SUMMARY_VERSION` + root + include_system in the cache key, `meta.index.variants` + a note when TUs disagree.
  - H4 viewer composed pending patches with `mergePatch` (drops `null`) → `hx/viewer/patch.js` (`composePatch` keeps deletes, refuses the non-composable delete-then-patch case) and a sequential FIFO of patches; Node unit tests + API delete-persistence test.
  - H5 overload suffix only on collision; slug collision → C++ ids always carry `(param types)`; `slug = prefix + '-' + hash6`, one-time rename of legacy files.
  - H6 truncation recorded a `from` outside the graph and dropped the queue; callers skipped globals; type expansion order-dependent → queue carries the parent, `truncate()` drains it; `add_globals` in both passes; `type_level` re-expands with a bigger budget.
  - H7 params only under signature change, attrs never, edge args only on equal counts → params and attrs always compared; args as multiset difference.
  - H8 `abspath` boundary → `realpath` on both sides.
- **Tests**: tautologies removed; conformance runs the invariants under depth 0, type depth 0/99, max-nodes, callers and exclusion, and asserts the caller round trip; new fixtures `tests/fixtures/c_variants` (build variants) and `tests/fixtures/cpp` (overloads, template, const method); `HX_REQUIRE_TOOLS=1` turns every skip into a failure (`tests/conftest.py`); `.github/workflows/ci.yml` installs all toolchains on Python 3.10/3.12; `tests/test_schema.py` validates graphs against `hx/schema/hx-1.schema.json`.
- **Docs/packaging/persistence**: base dependencies include `tomli` (py<3.11), MCP and Pyright with packaged Node.js; extras `dev` (including `jsonschema`), `e2e` and the compatibility `mcp` extra; README "Boundaries" and optional toolchain install commands; `Graph.from_dict` enforces the schema major (`SchemaError`); `hx/fsutil.py` atomic writes everywhere + `flock` around annotation read-modify-write; watch also tracks `compile_commands.json`, `Cargo.toml`, `pyrightconfig.json`, `CMakeLists.txt` even inside skipped build dirs.
- **Not done (deliberately)**: Playwright browser workflow tests (extra `e2e` reserved, no test written: the delete path is covered at the patch-composition and API levels); inotify watching; template instantiation expansion.

## Phase 4.6 — Real-project hardening, CVA6 review (done)
- **TLDR**: a second external review ran hx on CVA6 (403 cells, generate blocks, a parameterized FPU, a 17,270-bit packed configuration parameter). All eleven findings reproduced; the plan went through six review rounds before approval (each round's corrections are recorded in the plan file); everything is fixed with regressions that failed on the previous code. Schema major bumped to `hx/2`, package 0.3.0. Terms: specialization = one module elaborated with specific parameters; JS-safe integer = below 2^53.
- **Findings → fixes** (`hx/frontends/verilator_fe.py` unless noted):
  - H1 wide constants → `hx/values.py`: ints below 2^53 stay JSON numbers, wider values are canonical hex strings (`17270'h…` with width, `0x…` without), x/z keep bit patterns; values are encoded at indexing time so the cache never meets a wide int; `hx/graphio.py` is the one reader for every consumer (`parse_int` hook, chunked decimal conversion, no global digit-limit change); signatures show `fmt()` (`CFG=17270'h10000000…0000`), the viewer keeps the full literal in a tooltip; `diff.py` compares values with `values.equal` and SV signatures by shape.
  - H2 cache identity → executable resolved before the cache lookup; engine identity = `verilator --version`; argument files fingerprinted by expanded content (`$VAR`, `${VAR}`, `$(VAR)`) with Verilator's `-f`/`-F` nesting rules.
  - H3 specialized types → module-scoped types are identified by a layout fingerprint (`struct fp.fp_t@3f9a1c2e`), package types by name; scope-aware named-type recovery; the diff pairs relayouted types through their users.
  - H4 generated instances → recursive `<begin>` walk with scope paths; shorthand `.clk` → `.clk(clk)`, wildcard → `.clk(.*)`, XML expression rendering, never `…`.
  - H5 viewer layout → root cause isolated by delta debugging INSIDE the viewer (`tests/fixtures/viewer/layout-fail.json` is the 16-node minimum): dagre throws when a file group mixes a module INSTANCE with that module's own function/task node joined by a call edge (nested compounds + an intra-compound edge across ranks; reproduced with dagre 0.8.5 and 1.1.4 in Node, so no upgrade helps). Element-level fix: in hierarchy graphs a file's functions/tasks get their own group (`file · functions`); the full CVA6 graph at depth 3 then lays out with the default ranker in ~170 ms, 63 groups intact. Containment kept regardless: retry with the longest-path ranker, then without groups, then breadth-first, notices in the banner; `init()` never loses selection restore or SSE; `window.HX_TEST` (lastLayout, ranker, layoutErrors, failLayouts) and `window.HX_DEBUG` hooks for tests.
  - H6 anonymous SV types → named by first declaring context (`struct top_adv.cfg_i@…`), Verilator's `__typeimp…` names treated as anonymous; no line numbers.
  - H7 ranges → `loc.end_line` is the `endmodule`/`endfunction`/`endtask` line; the viewer centres a 120-line window on a distant call site.
  - H8 warnings → parsed from stderr, stored in the cached index, `stats.warnings` + `warnings_by_tag` + a note; the CLI prints errors and warnings apart.
  - H9 entry file → a module/function must be defined in the file; an instance path's file must define some module on the path.
  - H10 spelling → `__BRA__`/`__KET__`/`__DOT__`/`__0XX` decoded everywhere; both spellings accepted on input.
  - H11 version → `hx.__version__` is the single source (`dynamic` in pyproject); 0.3.0.
- **Compatibility (R0)**: `graphio.load_graph_dict` upgrades hx/1 in memory (lossless escape decoding only) and reports what it cannot settle; serve/MCP show `migration: pending`, the viewer a banner; `hx migrate` re-extracts every tracked entry into `.hx/staging-<pid>`, commits only when all succeed (snapshot, atomic move, backup `annotations.json.bak-hx1` written once, locked rewrite of annotation keys with a `meta.migrated` marker that `normalize()` preserves), maps module-scoped types by base id + users and anonymous types by identical layout + users, lists ambiguities and orphans, never guesses.
- **Fixtures/tests**: `tests/fixtures/sv_adv` (16,384-bit parameter, two `fp_t` specializations, generate `if`/`for` arrays, shorthand and `.*` ports, inline struct port, SELRANGE, env-dependent and nested lists), `tests/fixtures/legacy/hx1-cva6-like.json` (+ annotations), `tests/fixtures/viewer/layout-fail.json`; `tests/test_values.py`, `test_sv_adv.py`, `test_migrate.py`, `test_e2e_viewer.py` (Playwright, 7 tests, mandatory in strict mode; CI installs `.[dev,e2e]` and Chromium). 131 tests, no skips.
- **CVA6 verification (no `PYTHONINTMAXSTRDIGITS`)**: depth 0/3/all extract in ~2.5 s; `CVA6Cfg` is a 17,270-bit literal string, signature 197 chars; 402/402 instance edges with locations, 0 `…`; `gen_instr_scan[0]` accepted; 0 `__BRA__`, 0 `anon@L`; 61 SELRANGE warnings counted; 403/403 modules with real end lines; `fpnew_fma.fp_t` → two ids (32 and 64 bits, one user each); wrong entry file → exit 2; `TARGET_CFG` wt→warm hit→wb miss with `gen_cache_wb`; comment above `core/cva6.sv` → zero changes; full graph served at depth 3 → dagre on the first attempt (network-simplex, 63 groups), no page errors, SSE round trip visible in the DOM, `CVA6Cfg=17270'h10000000…` compact with the full literal in the tooltip.
- **Known limits**: edges do not avoid nodes; anonymous types that are used nowhere fall back to `anon#<hash>`; `hx migrate` handles tracked entries only (ad-hoc `.hx/graph.json` files are simply re-extracted); template instantiation remains unexpanded for C++.

## Phase 5 — Runtime (reserved)
- Not in scope. IR keeps `runtime: null`. Candidate strategies: C `-finstrument-functions` / gdb Python / uprobes; SV port probes via `verilator --trace`; Python `sys.setprofile`; Rust `tracing`.

## Risks / mitigations
- **Cross-compiler flags break libclang** → `--target` + sysroot auto-detect, `--extra-arg` escape hatch, per-TU error list in `meta.tu_errors`.
- **Macro-heavy register code** → macro spans + spelled args; `kind: macro` edges.
- **Large repos** → per-TU cache + multiprocessing + depth/max-nodes limits.
- **LSP frontends less exact** → `precision` surfaced in the viewer.
- **Dynamic dispatch / fn-pointers unresolved** → always listed in `unresolved[]`, shown as ghost nodes.

## Conventions
- Python 3.10+, dataclasses over pydantic for the IR, no network at runtime, vendored browser libs.
- Tests: `python -m pytest -q` from the repo root (venv at `.venv`). Fixture projects are copied to a temp dir per test.
- Do not commit on the user's behalf; the user decides when to commit.
- Keep this file's Status log current.

## Status log
- **2026-10-09** — Plan approved. Phase 1 implemented and verified (30 tests; cJSON, libuv smoke). Additions vs. original plan: top-level `globals{}` table, edge kind `ref`, operator kinds via libclang C API. Viewer tech adjusted from "TypeScript via esbuild" to vanilla ES modules + vendored libraries so there is no build step.
- **2026-10-09** — Phase 2 done. `hx serve` (FastAPI + uvicorn, lifespan watcher polling graph/annotations mtimes, SSE), `hx export`, `hx/annotations.py` (merge patch, recursive prune), viewer in `hx/viewer/` (vanilla JS, Cytoscape 3.34.3 + dagre 0.8.5 vendored). 42 tests (SSE tests run a real uvicorn thread because Starlette's TestClient buffers whole responses). Verified with headless Chrome screenshots in light and dark mode, console clean. Viewer extras beyond plan: `?theme=`, `?live=0`, caller side in tree, per-reason unresolved groups, global read/write panel, edge detail page.
- **2026-10-09** — Phase 3 done. SystemVerilog (verilator 5.020), Rust (rust-analyzer 1.99, installed via rustup `--profile minimal --no-modify-path`, binaries in `~/.cargo/bin`) and Python (pyright 1.1.414 via pip) frontends; fixtures under `tests/fixtures/{sv,rust,python}`; 62 tests green including a cross-frontend conformance test; viewer shows instance edges, bit-sized HDL layouts and node attrs (verified by headless Chrome).
- **2026-10-09** — Phase 4 done. `hx diff`, tracked entries with snapshots/history, `hx update`/`hx watch`, Claude Code hook installer, viewer diff mode and graph picker, MCP server (mcp 2.3.0). 76 tests green. Verified end to end on the C fixture (last-diff.md and viewer diff screenshot) and MCP tools through the in-memory client.
- **Open items carried forward**: viewer has no automated browser tests (only syntax check + headless render in dev loop); `annotations.view.hidden` is reserved but not yet used by the UI; export mode keeps edits in memory until downloaded; LSP frontends have no on-disk cache (each extraction restarts the server, ~2–4 s on the fixtures), so `hx update` on Rust/Python entries costs seconds per entry; SV internal-signal reads/writes per always block are not extracted (signals are listed in `attrs` only); Go profile (`gopls`) exists but is untested; `hx watch` polls (no inotify) — fine up to tens of thousands of files; MCP `extract` tool is synchronous (a slow extraction blocks that tool call); Phase 5 (runtime capture) remains reserved.
- **2026-10-10** — Phase 4.5 (hardening) done. External review verified line by line (8/8 findings reproduced, plus one worse than reported: pyright body hashes covered only the function name). Token-based `body_hash(text, lang)`, SV source-slice hashes, deterministic cache merge with complete keys, viewer patch FIFO with `composePatch`, C++ parameter-list ids, hashed slugs with legacy migration, traversal truncation/caller-globals/type-order fixes, broader diff, realpath confinement, JSON schema + loader check, atomic writes + file lock, CI workflow with `HX_REQUIRE_TOOLS=1`. Version bumped to 0.2.0 (cache `SUMMARY_VERSION` 2 invalidates old `.hx/cache`).
- **2026-10-09** — Dependency installation follow-up: MCP and Pyright with its packaged Node.js runtime now install with the base package; Python 3.10 retains its conditional `tomli` dependency. Preserved the compatibility `mcp` extra and documented developer/browser extras plus optional language toolchains. CI checks base installation before developer dependencies on Python 3.10/3.12. Verified clean wheel installs, dependency consistency and Pyright without system Node on both Python versions; 97 tests passed on each with no skips, plus all 4 standalone JavaScript tests.
- **2026-10-10** — Viewer edges switched from bezier to orthogonal routing (`curve-style: round-taxi`, 8px corner radius, direction follows the layout, turn 22px after the source so the cross run stays in the inter-rank gap, parallel edges staggered by 10px via `data.pi`, self-loops stay bezier). Taxi edges do not avoid obstacles; that is a known limit. Verified by headless screenshots in both layouts.
- **2026-10-10** — Phase 4.6 done (CVA6 review, 11 findings; plan reviewed six rounds). hx/values + hx/graphio, schema hx/2 + `hx migrate`, SV frontend rewrite (generate scopes, layout-identified types, context-named anonymous types, real ranges, warnings, entry validation, cache identity), viewer layout fallbacks with the minimized CVA6 reproducer, Playwright browser tests. 131 tests green in strict mode; every reviewer reproduction re-run on CVA6 without the digit-limit workaround. Version 0.3.0. Not committed (user commits).
- **2026-10-10** — Viewer: hide/show modules (eye on tree rows, detail-pane button, `h`). Hidden nodes are walls in `visibleSet()`: the node, its edges and everything only reachable through it disappear; shared routines stay. State in `annotations.view.hidden` (the slot reserved since Phase 2), so it persists, migrates with ids and carries into exports. Four Playwright tests (C fixture, export page, SV subtree).
