# Python API reference

Import the entry point from `hx.api`. The documented objects below form a curated
integration surface; frontend, lexer, cache, and traversal implementation helpers
are intentionally excluded. These signatures and docstrings are rendered from
the source. Start with the [scripting tutorial](../tutorials/python-api.md).

## Extraction

Python root defaults are unchanged by CLI discovery: `extract(root=".")` uses
the Python process's current directory and does not search for `.github`. Pass
the intended root explicitly for repeatable integrations.

::: hx.api.extract

## Graph and records

`Graph` contains dataclass records. Python edges use `src`/`dst`, while the JSON
representation uses `from`/`to`. Netlist-specific circuit data remains a dictionary.
See [graph format](graph.md) for field semantics and units.

::: hx.model.Graph
    options:
      members: [to_dict, to_json, save, from_dict, load]

::: hx.model
    options:
      members: [Loc, TypeUse, Param, Field, Enumerator, TypeDef, GlobalRefs, Node, GlobalVar, Edge, Unresolved]

## Load graph dictionaries

The loaders normalize wide values and upgrade older supported graph schemas in
memory; they do not rewrite a file or reconcile IDs by re-extraction.

::: hx.graphio
    options:
      members: [load_graph_dict, load_graph_with_report, MigrationReport]

## Compare and export

Pass `graph.to_dict()` to the differ and HTML builder. Load saved graphs through
the shared loaders before comparison so schema and value normalization apply.

::: hx.diff
    options:
      members: [diff_graphs, render_markdown]

::: hx.export
    options:
      members: [build_html, export_file]

## Project lifecycle

These operations read or write project state under `ROOT/.hx`. `track` replaces
an entry's option table; it does not merge omitted options from the previous
table. Pass keyword names from [configuration](configuration.md), not CLI flags.
`update` reports per-entry errors through `UpdateResult.error`; callers should
inspect every result. `watch` blocks until its stop condition is met.

Use `save_extraction(root, entry, graph)` for managed current graphs and history;
`refresh_default=True` also selects the entry for `.hx/graph.json`. With
`output="review.json", archive=False`, only that standalone file is written.
`SaveResult` includes `graph_path`, `previous`, `old_graph`, and refreshed `mirrors`.
`GraphSaveError.result` and `.committed` identify whether the authoritative file
was saved before a later compatibility-copy failure. `Graph.save()` remains a
low-level standalone writer and does not manage history.

::: hx.project
    options:
      members: [load_config, track, untrack, graph_path, find_graphs, save_extraction, SaveResult, GraphSaveError, snapshot, list_history, resolve_history, update, UpdateResult, watch, migrate]

## Annotation persistence

Use locked file operations for shared annotation updates. `patch_file` applies
JSON merge patch semantics; a Python `None` deletes a key. See
[annotation format](annotations.md).

`resolve_path(graph_path, explicit=None)` selects the destination without reading
annotation files or writing state.
`prepare_file` can select a legacy source for read-only use; its
`import_legacy=True` initializer copies one unambiguous source to the shared path
without overwriting existing notes. Viewer/MCP use import mode; export uses the
read-only mode. Standalone and explicit paths retain their existing defaults.

::: hx.annotations
    options:
      members: [resolve_path, prepare_file, empty, load, patch_file, replace_file]

## Exceptions

Extraction may raise `ValueError` for a malformed entry, or `FrontendError` and
its subclass `EntryNotFound` for frontend/lookup failures. The latter carries
`suggestions`. File APIs can also raise `OSError`; JSON loaders can raise
`ValueError`, including `SchemaError` for unsupported schema versions.
`Graph.from_dict` checks the schema major; it is not a complete JSON Schema
validator.

::: hx.frontends.base.FrontendError

::: hx.frontends.base.EntryNotFound

::: hx.model.SchemaError
