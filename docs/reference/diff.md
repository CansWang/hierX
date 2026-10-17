# Structural diffs

Compare arbitrary saved graphs:

```bash
hx diff old.json new.json
hx diff old.json new.json --format json -o changes.json
hx diff old.json new.json --exit-code
```

Extract an entry twice through CLI, updates, MCP, or the viewer, or take a viewer
baseline, then compare its current graph with history. Tracking is optional:

```bash
hx diff --entry src/main.c:app_run
hx diff --entry src/main.c:app_run --since prev
```

`--since` accepts `prev`, an exact snapshot identifier (old timestamp identifiers
remain accepted), or an ISO time. Resolution uses the graph's generation time and chooses
the latest snapshot not later than the requested time, or the earliest available
snapshot if the requested time predates history. `--exit-code` returns 1 for a
nonempty diff; normal display returns 0 even when there are changes.

## What changes are reported

The differ compares nodes, signatures, parameters/directions, body hashes,
globals, type layouts, edges and their arguments, and unresolved records. Netlist
comparisons also include wiring, models, definitions, and parameters. Equivalent
numeric value spellings compare equally. Line-number drift and formatting-only
body edits do not independently register as changes.

IDs are important: renaming a function or changing an overload's parameter types
can look like removal plus addition. Some HDL layout changes are paired through
the types' users. Build-configuration changes and schema migrations can cause
identity churn; compare graphs from the intended configuration.

## JSON shape

The current diff schema is `hx-diff/1`:

| Key | Contents |
|---|---|
| `schema` | `hx-diff/1` |
| `old`, `new` | Generation/entry metadata and node counts |
| `summary` | Counts by category, a combined `total`, and boolean `any` |
| `nodes`, `types`, `globals` | `added`, `removed`, and ID-keyed `changed` records; `nodes.removed_info` keeps each removed node's name, kind and location |
| `edges` | Added/removed edge records and `args_changed` |
| `unresolved` | Added/removed unresolved records |
| `circuit` | Netlist declaration and connectivity change sections |

Use `summary.any` to decide whether there are changes. Individual counters can
overlap, so do not infer a count of unique changed objects by summing them.
Change records carry category-specific old/new values. HTTP responses can add
`since`, `since_generated` and a `markdown` rendering; those are wrappers around the core diff.

Python callers use `diff_graphs(old_dict, new_dict)` and
`render_markdown(diff, new_dict)`. Rendering limits displayed items per section;
the JSON diff retains the complete data. See the [Python reference](python.md).
