# Graph format

The current graph schema is `hx/4`. Download the
[JSON Schema](hx-4.schema.json) for field-level validation. Consumers should ignore
unknown fields: additions within a major version are compatible. Unsupported
majors are refused by the shared readers.

Rust trait methods include the self type and trait arguments, for example
`rs:src/lib.rs::<Item as Convert<String>>::convert`. Older Rust graphs are read
without guessing new IDs and flagged for `hx migrate`. Migration preserves
history and backs up notes; ambiguous mappings are reported. Verification marks
are cleared when Rust token corrections change a body hash.

## Top-level fields

| Field | Meaning |
|---|---|
| `schema`, `generated` | Format version and generation timestamp |
| `root`, `lang`, `entry` | Project root, language, and stable entry node ID |
| `nodes` | ID-keyed functions, methods, modules, tasks, instances, or devices |
| `types` | ID-keyed structs, unions, classes, enums, typedefs, and related type records |
| `globals` | ID-keyed touched globals and function-local statics |
| `edges` | Relationships with `from`, nullable `to`, `kind`, source location, and arguments |
| `unresolved` | Targets reached but not expanded, with `from`, name, reason, and optional ID/location |
| `meta` | Extraction options, indexing statistics, notes, diagnostics, migration, and optional provenance |
| `circuit` | Netlist connectivity and declaration data; absent for other frontends |

A node includes `id`, `kind`, `name`, `qualname`, `lang`, `loc`, `signature`,
`depth`, `body_hash`, `precision`, `params`, `returns`, `globals`, `calls`, and
frontend-specific `attrs`. `loc` contains a file and line, with optional column
and ending line. Depth is the minimum traversal distance: 0 for the entry,
positive for callees/children, negative for callers/parents.

`calls` lists expanded target IDs. Use `edges` for arguments, relationship kind,
call-site locations, and unresolved relationships. Edge kinds include `call`,
`macro`, `fnptr`, `ref`, and `instance`. An unresolved record can mean a depth
boundary, an exclusion, a system header, no definition, or an indirect target;
read its `reason` rather than assuming extraction failed.

## Extraction provenance

New Python and CLI extractions include optional `meta.provenance` (version 1).
Existing graphs need no migration and retain unknown provenance when absent.

| Field | Meaning |
|---|---|
| `version`, `run_id` | Provenance format and UUID identifying the extraction |
| `started`, `completed`, `hx_version` | UTC run times and extractor version |
| `git` | `status`, actual `repo_root`, full `commit`, nullable `dirty`, and `changed_during_extract` |
| `inputs` | `coverage: observed`, sorted `files` manifest, SHA-256, and change-detection flag |
| `options_sha256` | Canonical JSON hash of effective replay options, excluding entry and root |
| `graph_sha256` | Canonical JSON hash of graph fields excluding root, generation time, and metadata |

Git status is `ok`, `no-repo`, `unborn`, or `unavailable`. Discovery starts at the
resolved entry source, so a submodule or worktree can have a different Git root
from the `.github` directory used to place `.hx`. Hx-generated state is excluded
from dirty detection. Detected Git changes during the run also record
`at_completion`; Git failures become diagnostics rather than extraction failures.

Each input has `path`, nullable `sha256`, and `status`: `ok`, `missing`,
`unreadable`, or `changed`. Paths inside the project are relative; external ones
are absolute. Observations include C/C++ TU dependencies and compilation databases,
Verilator design/argument files, netlist dependencies/include probes, and LSP
documents read by hx plus nearby recognized project configurations. Cache hits
retain observations. Available dependency timestamps and before/after hashing
checks flag detected file changes.

Coverage remains observed: server-private inputs, environment settings, and
changes that hx cannot detect are not fully captured. This metadata is useful
for identifying runs, not a guarantee of exact reproducibility. Hashes use
SHA-256; canonical JSON sorts dictionary keys and preserves array order.
Provenance-only changes do not count as structural diffs.

## Types, units, and precision

Parameters carry a spelled `type`, optional `type_ref`, `dir`, and `dir_source`.
Directions are `in`, `out`, or `inout`; their source is explicit language data,
a heuristic, or a user override in annotations.

C/C++ type `size`, `align`, and field `offset`/`size` are bytes. Bitfields have
`bit_offset` and `bit_width`. SystemVerilog sizes and offsets are bits, with
packed-struct offsets measured from the most significant side. Incomplete types
and language-server types can omit layouts; do not replace missing sizes with 0.
Typedefs refer to their target through `underlying_ref`.

Node precision is `exact` for compiler/elaborator-derived records, `lsp` for
language-server data, and `syntax` for native netlist parsing. The
[language guides](../getting-started/install.md#choose-a-frontend) describe the
limitations of each.

## Identity and hashes

Typical IDs are `c:src/main.c::app_run`,
`cpp:src/bus.cpp::hw::Bus::write(const Reg &)`, and
`sv:rtl/core.sv::top.u_core_a`. They are intended to survive regeneration of the
same build configuration, so annotation keys remain useful.

C/C++ non-external symbols and all C/C++ types carry defining-file identity.
Different translation-unit type layouts or targets can produce `@<8hex>` variants.
C++ parameter types distinguish overloads. Python nested functions include their
enclosing function; rare residual collisions can add position-dependent suffixes.
HDL module-scoped types carry layout identity, so changing the layout changes the
ID. Build-configuration changes can legitimately change IDs.

`body_hash` hashes tokens, not program semantics. Whitespace and comments normally
do not change it; renamed variables, literal contents, operator adjacency, and
Python indentation do. HDL modules cover their source body. Netlist hashes ignore
formatting, case, comments, and unrelated statement ordering. Verification marks
store a reviewed hash and become stale when that hash changes.

## Wide values

Integers with magnitude below `2**53` are JSON numbers. Wider values are lossless
canonical hex strings, with an HDL width prefix when known. Values containing
x/z bits remain bit-pattern strings. Do not coerce these values through a
JavaScript floating-point number. The differ compares equivalent numeric forms
numerically.

## Netlist circuit data

Netlist graphs use `lang: sp`. Decks and definition-rooted views are `module`
nodes, `X` occurrences are `instance` nodes, and primitive elements are `device`
nodes. Occurrence IDs include the deck, for example `sp:ota.sp::xa.m_load_1`.
A definition-rooted view uses its defining file, such as
`sp:lib/devices.inc::@nch_wrap`. Guarded occurrences append `#<guard_id>`.

| `circuit` field | Meaning |
|---|---|
| `dialect`, `deck`, `root` | Parse dialect and extraction context |
| `files`, `probes` | Included files/sections and attempted resolution paths |
| `definitions`, `models`, `params` | Scoped declarations and their resolution status |
| `nets`, `terminals`, `ports` | Connectivity and per-node bindings |
| `directives`, `control_blocks` | Preserved statements and unexecuted control text |
| `diagnostics` | Structured messages such as missing includes/models or unsupported statements |

Resolution can be `found`, `alternatives`, `ambiguous`, `binned`, `shadowed`, or
`missing`. Local scopes shadow outer declarations. Expressions stay symbolic;
conditional branches retain guards. Missing includes and unsupported directives
produce diagnostics while extraction continues where possible. Dependency files
and include probes also appear in metadata for caching and watching.

## Older graphs and migration

Shared readers upgrade `hx/1`, `hx/2` and `hx/3` in memory and can attach a migration
report. That does not reconstruct IDs requiring new extraction rules.
`hx migrate` re-extracts tracked entries into staging, then maps annotation keys
and creates a one-time backup. Ambiguous/unmatched mappings are reported rather
than guessed. Previous history retains its old IDs, which can cause one-time
removed/added churn in the first post-migration diff.
