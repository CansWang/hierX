# Script extraction and comparisons with Python

This tutorial uses the native netlist frontend, so it needs no external compiler,
language server, or simulator. From the checkout, prepare a fresh workspace and
remember the script's absolute path:

```bash
HX_TUTORIAL_REPO="$PWD"
python examples/prepare.py netlist /tmp/hx-api-tutorial
cd /tmp/hx-api-tutorial
python "$HX_TUTORIAL_REPO/examples/inspect_graph.py"
```

The script below is included directly from the tested example file. It extracts a
`Graph`, round-trips JSON, visits nodes and edges, changes a resistor in the copied
deck, renders a diff, and exports the changed graph. It restores the source deck
when finished.

<!-- hx:include examples/inspect_graph.py -->

Expect an entry beginning `sp:ota.sp::`, nodes with `precision` set to `syntax`,
a non-empty change report, and three artifacts under `.hx/`: `before.json`,
`after.json`, and `review.html`.

## Use the same API for code

Change the entry and frontend options to extract C, HDL, Rust, or Python.
For example, in the [prepared C workspace](c-review.md):

```python
from hx.api import extract

graph = extract("src/main.c:app_run", root=".", depth=3, jobs=1)
entry = graph.nodes[graph.entry]
print(entry.signature)
print([(p.name, p.dir, p.dir_source) for p in entry.params])
```

`depth=None` removes the depth limit in Python; on the CLI use `--all`.
Pass sequences for repeated arguments, such as `exclude=["third_party/*"]`,
`extra_args=["-DMODE=1"]`, or `search_paths=["models"]`.
`lsp_cmd` is an argument sequence, not a shell command string.

## Handle failure and partial results

`extract` raises `ValueError` for malformed entries, `FrontendError` for frontend
failures, and its subclass `EntryNotFound` for lookup failures. Catch those around
extraction and show the error to the caller. Inspect `graph.unresolved`,
`graph.meta`, and netlist `graph.circuit["diagnostics"]` for incomplete results
that do not abort extraction.

Extraction returns an in-memory object and may write caches; call `save` yourself
to persist a graph. `Graph.load` normalizes and upgrades older supported schemas
in memory. `Graph.from_dict` expects the current schema and does not perform that
upgrade. Dictionary consumers can use `load_graph_dict` instead.

Continue with the [Python API reference](../reference/python.md) for model fields,
exceptions, annotation operations, and project-level tracking.
