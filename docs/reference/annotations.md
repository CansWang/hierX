# Annotation format

Annotations are human-owned data in `.hx/annotations.json`, shared by graphs
within the same state directory, including current graphs and historical snapshots.
Standalone graphs outside `.hx` use adjacent notes. `hx serve --annotations FILE`
and `hx export --annotations FILE` override those defaults. Source lookup overrides
and a graph's embedded root do not change annotation selection.
They are keyed by graph IDs and are not embedded into regenerated
graphs. HTML export includes a snapshot of them.

## Legacy sidecars

An existing shared annotation file always wins. When it is absent, hx checks
`.hx/graphs/annotations.json`, `.hx/history/*/annotations.json`, and the selected
managed graph's adjacent note file. Aliases of the same physical file count once.
The graph itself is never an annotation candidate.

Viewer/MCP initialization copies exactly one legacy source to the shared path
atomically under the annotation write lock, preserving the original bytes and
source file. A legacy source must be a JSON object with schema `hx-ann/1` or no
schema. No fields are normalized during copying. With no legacy notes, startup
does not create an empty annotation file.

Export reads an unambiguous legacy source without importing it or changing source
state. Multiple sources, invalid documents, and unreadable files produce an
actionable error. Use `--annotations FILE` to choose a file for serve/export;
for MCP, copy your selected file to `.hx/annotations.json` before startup.
Explicit overrides bypass automatic import. Files are never merged automatically.

Schema migration validates legacy selection during staging and imports only
after every extraction succeeds. Annotation keys are then migrated using the
existing one-time backup behavior. Failed extraction staging leaves legacy notes
unchanged and creates no shared note file. Reserved `annotations.json` files are
excluded from graph pickers and history listings.

## Document shape

```json
{
  "schema": "hx-ann/1",
  "nodes": {
    "c:src/dma.c::dma_start": {
      "note": "Reviewed register writes",
      "tags": ["dma", "reviewed"],
      "params": {"ch": {"dir": "inout", "note": "Updated in place"}}
    }
  },
  "types": {},
  "globals": {},
  "view": {"hidden": [], "pinned_positions": {}},
  "meta": {}
}
```

| Bucket | Supported content |
|---|---|
| `nodes[ID]` | `note`, `tags`, `verified_body_hash`, `collapsed`, and `params[NAME]` direction/note overrides |
| `types[ID]` | `note` and `fields[NAME].note` |
| `globals[ID]` | `note` |
| `view` | `hidden` node IDs and `pinned_positions[ID]` with x/y coordinates |
| `meta` | Migration bookkeeping maintained by hx |

A verification mark pins the body's reviewed hash. The viewer compares that
value with the newly extracted node hash to flag stale verification. Direction
overrides are displayed with user provenance; they do not change extraction
heuristics in the graph itself.

## Merge patches

`PATCH /api/annotations` and Python `patch_file` merge objects recursively, replace
arrays, and delete keys whose patch value is JSON `null` (Python `None`). Empty
annotation entries are pruned after updates. For example:

```json
{"nodes": {"c:src/dma.c::dma_start": {"note": null}}}
```

This deletes the note and preserves other fields. `PUT /api/annotations` replaces
the annotation document after normalization. Both HTTP writes return a wrapper
containing `rev` and `annotations`; send the annotation document or patch itself
as the request body, not that response wrapper.

Locked file operations serialize read-modify-write across the local viewer and
MCP processes. Files are replaced atomically. The HTTP revision is local to a
running server and is not an optimistic-concurrency token. Shared writes from
different machines on a network filesystem are not supported.

For examples, see [HTTP annotations](http.md#patch-apiannotations) or the
[Python API](python.md#annotation-persistence).
