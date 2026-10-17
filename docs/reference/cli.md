# CLI reference

The command sections below are generated from hx's argparse parser at build time.
Use `hx COMMAND --help` for the exact help from your installed version.

## Entry syntax

An entry is `FILE:SYMBOL`, split at the first separator after any Windows drive
prefix. Rust/C++ `::` inside SYMBOL is preserved. Without `--root`, its file
path is relative to the run directory; the first `.github` upward from the real
source file selects the project root. With an explicit `--root`, the file path is
relative to that root. Without a marker, automatic discovery uses the run
directory. See [root and state selection](configuration.md#choose-the-project-root).

| Frontend | Symbol examples |
|---|---|
| C/C++ | `app_run` or `run` (bare name; see C++ limitations in the language guide) |
| Python/Rust | `app_run`, `outer.helper`, or a qualified function/method |
| HDL | `top` or `top.u_core.u_alu` |
| Netlists | `.` for a deck; `xa.m1` for an occurrence; `@opamp` or `@scope/name` for a definition |

For HDL and netlist paths, the named file must contain a relevant definition or
an accepted location on the path. C/C++ lookup can use a unique definition in
another file and records that fallback in metadata notes. Quote globs and instance paths containing shell
metacharacters. Use `--all` for unlimited depth, `--depth 0` for only the entry,
and `--include-callers` to include the caller/parent side with negative depths.

## Default graph lookup

`serve` and `export` prefer an existing run-directory `.hx`, otherwise the `.hx`
at the first `.github` found upward from the run directory. A missing repository
state directory, or an empty local one, is an error rather than a reason to
continue upward. Within the chosen state, `graph.json` wins over sorted
`graphs/*.json`. Explicit graph paths bypass lookup; `serve --root` only controls
source lookup. See [graph selection](configuration.md#find-a-graph-for-serve-or-export).

## Outputs and exit status

| Command | Output or effect | Exit status |
|---|---|---|
| `extract` | Per-entry current graph, compatibility `.hx/graph.json`, and previous history; `-o` writes only FILE | 0 on completion, including graphs with diagnostics; 2 for handled extraction or save failures |
| `serve` | Browser viewer and HTTP API, default `127.0.0.1:8765` | Long-running; Ctrl-C stops it; 2 for handled initialization failures |
| `export` | HTML next to the graph unless `-o` is supplied | 0 on completion; 2 for handled graph, annotation, or I/O errors |
| `track` | Replaces/removes one tracked entry table, or lists entries | 0 for normal operations |
| `update` | Tracked graphs, previous snapshots, and `.hx/last-diff.md` | 0 when every entry succeeded; 2 when any entry failed or nothing is tracked, except in `--hook` mode, which always exits 0; per-entry errors are in the report either way |
| `watch` | Repeated updates after a quiet period | Long-running; `--once` runs one update and exits 0; 2 when nothing is tracked |
| `diff` | Markdown or JSON to stdout or `-o` | Normally 0; `--exit-code` returns 1 for differences; handled missing entry/history returns 2 |
| `migrate` | Re-extracted tracked graphs and migrated annotations | 0 on success/noop; 2 on reported extraction failure |
| `hook` | `print` writes the JSON snippet; `install` merges it into `settings.json` | 0 after print or install, including when the hook is already present; 2 when the settings file is not valid JSON or cannot be written. The installed command, `hx update --quiet --hook`, always exits 0 so it never blocks an editing session |
| `mcp` | stdio protocol, or JSON configuration with `--print-config` | Long-running server; 2 for handled dependency/annotation initialization failures |
| `netlist check` | Oracle report with `scope` and `dialect` lines; `--json` includes the rendered closure (ngspice) | 0 agree, 1 mismatch, 2 oracle unavailable (simulator missing, rejected the deck, printed no listing, or exceeded `--timeout`) or handled extraction failure |
| `netlist net` / `netlist uses` | Read-only saved-graph queries; `--json` returns full records | 0 success, 2 missing/ambiguous item, invalid arguments or graph |

These are command-specific statuses, not a guarantee that every possible I/O
exception is converted into a particular code. See
[project configuration](configuration.md) for tracked option names and persistence,
and [troubleshooting](../troubleshooting.md) for incomplete results.

<!-- hx:cli -->
