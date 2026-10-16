# Annotation format

Annotations are human-owned data in `.hx/annotations.json`, normally shared by
all tracked graphs in a project. A custom `hx serve --annotations FILE` can use
another file. They are keyed by graph IDs and are not embedded into regenerated
graphs. HTML export includes a snapshot of them.

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
