# Project configuration and files

## Choose the project root

Without `--root`, entry-based CLI commands resolve the entry file from the run
directory, follow source symlinks, and walk upward from the real source's parent.
The **first directory containing a `.github` directory** becomes the project
root. hx places `.hx` beside that marker and uses the root for IDs, frontend
configuration discovery, and replay. If no marker is found, the root is the run
directory, even when the source lives elsewhere.

For `watch`, `track --list`, `update` without entries, MCP startup, hooks, and
migration, the upward search starts at the run directory. `extract`, `track`
add/remove, `diff --entry`, `netlist check`, and updates with explicit entries use
the source-based search. A batch update cannot implicitly span several project
roots; pass `--root` to select a single project explicitly.

```text
outer/
├── .github/
└── component/
    ├── .github/
    ├── .hx/             <- state for component/src/main.c
    └── src/main.c
```

Discovery stops at `component/.github`; it never continues to `outer/.github`.
A submodule without its own `.github` uses the first marker above it instead.
Git metadata is not consulted: neither a `.git` directory nor a submodule `.git`
file is a marker, and a regular file named `.github` is not a marker either.

An explicit `--root` bypasses discovery. Entry paths then retain their existing
root-relative interpretation. In particular, `--root .` pins extraction/state to
the run directory. Without an explicit root, entry paths and supplied file/path
options are invocation-relative; CLI options such as `--deck`, `--search-path`,
`--compile-commands`, `-f`, and `--sv-file` are normalized before extraction so
replay works from another directory. Output paths remain invocation-relative.
Exclusion globs and paths inside compiler arguments or argument files continue to
follow the frontend's project-root rules.

Automatically resolved entry keys are root-relative when inside the project,
absolute otherwise. Calling `track` from the root or a source subdirectory with
equivalent file paths therefore addresses the same entry. Python APIs retain
their existing explicit-root contracts; `hx.api.extract` still defaults to the
Python process's current directory.

## Find a graph for serve or export

With no graph argument, `hx serve` and `hx export` first select `<rundir>/.hx` if
it exists. Only if it is absent do they search upward from the run directory for
the first `.github` and select that project's `.hx`. They never search from a
previous extraction's source path or continue to an outer marker when the first
marked project lacks state.

Inside the selected directory, `graph.json` takes priority; otherwise the first
regular `graphs/*.json` file in filename order is selected, excluding reserved
`annotations.json` sidecars. Existing local state shadows repository state even
when empty or invalid. Missing state or graphs
produce exit status 2; lookup does not create a directory or start a server.

An explicit graph path is invocation-relative and bypasses discovery, with no
fallback on failure. `serve --root` only overrides source lookup; it does not
change graph selection. Graphs within `.hx`, including historical snapshots,
share that state directory's `annotations.json`. Standalone graphs use adjacent
notes; `--annotations` overrides either default. Symlinks follow the graph's
owning state location, independently of its embedded source root.
The graph picker and history stay attached to the selected state directory.

Viewer/MCP initialization imports one unambiguous legacy sidecar when the shared
file is absent. Export reads it without creating the shared file. See
[annotation compatibility](annotations.md#legacy-sidecars) for selection and errors.

Existing `.hx` directories are not relocated or merged automatically. A legacy
local `.hx` can therefore shadow a newer repository graph. Pass that graph explicitly to select
it, or use `--root .` when extracting to maintain the local workflow. See
[troubleshooting](../troubleshooting.md#state-is-in-an-unexpected-directory).

## Track entry points

`hx track ENTRY` adds or replaces an entry table in `.hx/config.toml`.
`hx track --list` lists tables; `hx track ENTRY --remove` removes one. Tracking
does not immediately extract. Run `hx update` afterward.

```toml
[watch]
interval = 2.0
debounce = 1.0
history = 20
paths = []

[[entries]]
entry = "src/main.c:app_run"
depth = 3
type_depth = 2
include_callers = true
exclude = ["third_party/*"]

[[entries]]
entry = "ota.sp:."
depth = 2
dialect = "ngspice"
search_paths = ["models"]
```

`interval` is polling seconds, `debounce` is quiet seconds before updating,
`history` is the maximum retained snapshots per entry, and `paths` optionally
limits watched source subtrees. Build-description files and netlist dependency
probes are also watched. Paths are interpreted in the project root context.

## Tracked extraction options

The entry tables accept Python API keyword names:

| Group | Keys |
|---|---|
| Traversal | `depth`, `type_depth`, `include_callers`, `include_system`, `exclude`, `max_nodes` |
| C/C++ and common compiler flags | `compile_commands`, `resource_dir`, `extra_args`, `jobs` |
| Frontend | `lang` |
| HDL | `sv_files`, `filelist`, `top`, `verilator` |
| LSP | `lsp_cmd`, `lsp_timeout` |
| Netlists | `dialect`, `deck`, `search_paths` |

Omitted keys use `extract` defaults. The CLI supports the flags listed under
[`hx track`](cli.md#hx-track); additional supported keys can be supplied in TOML
or via Python. Use arrays for `extra_args`, `lsp_cmd`, `sv_files`, and
`search_paths`. TOML cannot express Python `None`; use the Python API for an
unlimited `depth=None` one-off extraction.

Calling `track` again replaces the previous table for that entry, so provide the
options you want to retain. MCP extraction has a separate merge rule: omitted
or null options inherit existing tracked values before explicit overrides apply.
See [MCP extract](mcp.md#extract).

Older configs may contain a relative `compile_commands` path. A working
invocation-relative path keeps priority; if it is absent, hx also tries that path
under the selected project root. This lets existing tables work when updated
from a subdirectory without rewriting the configuration.

## Generated project state

| Location | Contents |
|---|---|
| `.hx/graph.json` | Compatibility copy of the latest default CLI extraction; follows later saves of that entry |
| `.hx/graphs/<slug>.json` | Authoritative current graph per entry, including default CLI, updates, MCP, and managed viewer extraction |
| `.hx/history/<slug>/` | Immutable previous graphs, named with UTC time, commit prefix, and run ID |
| `.hx/last-diff.md` | Most recent project update report, including per-entry errors |
| `.hx/annotations.json` | Shared notes, overrides, verification, and view state |
| `.hx/cache/` | Frontend caches; bypass with `extract --no-cache` |
| `.hx/lsp.log` | Verbose language-server traffic when enabled |

Graph filenames contain a readable prefix plus a hash of the entry text. Discover
them with the viewer picker, `list_graphs`, or Python `graph_path`; do not construct
a slug by replacing punctuation yourself.

All managed writers archive an existing current graph before replacement, even
when the new graph has no structural changes. First extraction has no history;
the viewer's baseline button can archive the current version immediately.
Repeated baselines reuse identical saved bytes. Default retention keeps 20
previous versions per entry; `watch.history = 0` disables history, and negative
values are invalid. Retention deletes old files without rewriting retained ones.

`hx extract -o FILE` writes only that file, including provenance, and does not
create managed current graphs or history. Frontend caches may still be written.
Viewer re-extraction of a standalone file archives its previous bytes and saves
back to that file. Writers refuse destinations inside `.hx/history/`.

Legacy default graphs are preserved as per-entry current files before a default
entry switch. Existing snapshots keep their names and bytes. New filenames have
the form `20261014T203012.123456Z-a1b2c3d4e5f6-dirty-<run-id>.json`; `nogit` marks
a source outside Git and `unknown` marks unavailable or legacy revision data.
The revision belongs to the saved graph, not the repository at snapshot time.

Saves use a project lock and atomic individual file writes. The per-entry file is
authoritative: a compatibility-copy failure can occur after it commits. That
failure is reported with the committed path; the next managed save repairs the
copy. Failed extractions leave current graphs alone. Failed update entries do
not stop other entries; inspect `UpdateResult.error` or the update report.

The watcher skips generated/build directories by default while still tracking
known build-description filenames, such as `compile_commands.json` and
`Cargo.toml`. It polls modification times; it does not use inotify.

### Rust configuration inputs

Rust extraction and watching share configuration discovery. Candidates include
`Cargo.toml`, `Cargo.lock`, `rust-toolchain`, `rust-toolchain.toml`, `.cargo/config`,
and `.cargo/config.toml` at the extraction root and each ancestor, plus `config`
and `config.toml` under `$CARGO_HOME` (default `~/.cargo`). Relative `CARGO_HOME`
paths are resolved from the extraction root, where the language server starts.
Both legacy and current spellings are observed; hx does not resolve their
precedence or inspect credentials. This follows the working-directory scope of
[Cargo configuration](https://doc.rust-lang.org/cargo/reference/config.html#hierarchical-structure)
and [Rustup toolchain files](https://rust-lang.github.io/rustup/overrides.html).

Missing candidates are retained so creation, editing, and deletion change the
watch signature. These inputs remain watched with restricted `watch.paths`,
before the first successful extraction of a tracked Rust entry, and with
`run_first=False` in the Python watch API. Saved provenance inputs also contribute
dependencies, including paths outside the project; older Rust graphs use candidate
discovery even without provenance. This observes potential inputs rather than
proving which configuration was effective. Environment overrides, server-private
inputs, and edits that preserve timestamps remain outside this freshness guarantee.
