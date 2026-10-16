# Troubleshooting

## hx is missing or imports fail

Activate the environment where hx was installed, run `python -m pip check`, and
check `hx --help`. MCP clients launched from a desktop may need an absolute path
to that environment's `hx` executable. Pyright's packaged Node.js runtime is
separate from the optional standalone Node executable used by viewer tests.

## C/C++ extraction cannot find headers or an entry

Use the compilation database for the build configuration you intend to inspect.
Pass `--compile-commands build` or the actual JSON path. Confirm its include paths,
defines, language flags, and target SDK headers are available on this machine.
Install `clang` for automatic resource-header discovery or supply
`--resource-dir`. Add `-v` to see translation-unit diagnostics.

Use the file defining the entry. C++ namespace-qualified entries containing
`::` conflict with the final-colon entry separator; use a bare name. C/C++ lookup may use a unique definition in another file and records a note; several
overloads in the same file currently select the first indexed match. HDL/netlist
entry errors enforce their path/file constraints and offer candidates. A graph can still be written when some translation units fail: inspect
`meta.index`, `meta.tu_errors`, and the printed warnings.

## The graph is smaller than expected

Increase `--depth` or use `--all`; use `--include-callers` for upward traversal.
Inspect `unresolved` reasons and `meta.truncated` (a `--max-nodes` cap). Remove
unintended excludes or use `--include-system` to expand system definitions.

A missing target is not always a parser bug: declaration-only functions and
indirect calls may be unresolved by design. LSP graphs contain only calls the
server reports and have no globals or memory layouts. Check the selected graph
in the viewer picker before comparing counts.

## Verilator reports missing packages or wrong hierarchy

Supply the real project's ordered argument file and configuration environment.
Use `-f`, `--top`, and the relevant include/define/parameter flags. Recursive file
discovery does not know package ordering or target selection. Quote generate-array
paths in the shell. Use the entry file defining a module on that instance path.
Warnings and errors are counted separately; inspect `-v` output.

## A language server times out

Use the project root containing the Cargo or Pyright configuration. Confirm
`rust-analyzer` and `rust-src` are installed for Rust. Increase `--lsp-timeout`
and use `-v` to inspect `.hx/lsp.log`. Override a server path with `--lsp-cmd`.
Server startup happens for each extraction, even after a previous successful run.
Go is experimental and has no integration tests.

## Netlists

Only `spice` and `ngspice` parsing are currently supported. HSPICE, Xyce, and
Spectre profiles are planned; finding their executables does not enable parsing.

Inspect `circuit.diagnostics`, the summary counts, and `-v` output. Common causes:

| Diagnostic or symptom | Action |
|---|---|
| `missing-include` | Check include spelling, `.lib` section, and repeated `--search-path` directories; inspect probes |
| `missing-definition`, `missing-model` | Supply the deck/library context with `--deck`; confirm declarations exist in the selected scope/section |
| `terminal-count-mismatch` | Compare the occurrence's nets with the resolved definition's port count |
| `duplicate-definition`, ambiguous lookup | Resolve duplicate declarations in the same scope; hx does not use last-wins lookup |
| Unsupported/unknown statement | Read the preserved source and diagnostic; it may be outside current dialect coverage |
| Oracle unavailable | Confirm ngspice is installed and the deck has numerical parameters and required model implementations |

Extraction continuing does not mean diagnostics are harmless. Parameters are
symbolic, guarded branches are retained, and `.control` text is never executed.
Use `hx netlist check` as an optional structural comparison, not as a substitute
for your simulator's full validation. Its status 2 describes unavailable checks,
which differ from status 1 mismatches.

Override ngspice with `--ngspice PATH` or `HX_TOOL_NGSPICE`. An explicit executable
override does not silently fall back to another installation.

## Notes or verification look wrong after a change

Notes attach to stable IDs, so renaming a symbol, changing a layout-identified HDL
type, or selecting another build can orphan them. Verification records a body
hash and becomes stale after a token change. Review the change before verifying
again. Use `hx migrate` for older schemas; it reports ambiguous/unmapped keys and
backs up annotations rather than guessing.

## State is in an unexpected directory

Automatic extraction starts from the real source file and stops at the first
`.github` directory upward. In nested repositories or submodules with their own
marker, it does not continue to an outer repository. Without a marker it uses
the run directory; a `.git` directory or file does not trigger discovery.
`--root .` explicitly keeps state in the run directory, while `--root PATH`
selects another project. The Python API does not perform CLI root discovery.

`serve` and `export` first use an existing run-directory `.hx`. Even an empty one
shadows the repository graph. Only if local state is absent do they find the
first `.github` upward from the run directory. If that root lacks `.hx` or a graph,
they return status 2 rather than reading an outer repository's graph. Nothing is
created during lookup. An explicit graph path bypasses discovery:

```bash
hx serve /path/to/repo/.hx/graph.json
```

Do not use `serve --root` to select a graph; that option controls source lookup.
Existing state is not moved or merged. Check the printed graph and annotation
paths when opening a project after changing its root convention. A different
project root can change IDs relative to older graphs and annotation keys.

A batch update with source entries spanning several automatic roots is rejected
before writing. Run one project at a time, or use an explicit `--root`.

## The viewer or diff has no data

Run `hx extract` or `hx track` followed by `hx update`, then select the intended
graph. Tracked history appears after a second update or a viewer baseline.
`POST /api/extract` needs replay options in `meta.extract_args`; regenerate older
or external graphs through the CLI first. `--no-extract` disables replay.

Use `hx serve` for live annotations, source snippets, and re-extraction. Exported
HTML has no server to persist changes. If the viewer reports a layout fallback,
it still permits inspection; reduce depth or hide branches to simplify the graph.
