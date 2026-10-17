# MCP tools

`hx mcp --root ROOT` runs a stdio MCP server over project graphs.
`hx mcp --print-config` prints a client configuration snippet. MCP and HTTP are
separate interfaces: the viewer's HTTP port is not the MCP transport. See the
[agent walkthrough](../tutorials/agents.md) for setup and example calls.

Without `--root`, CLI startup searches upward from the run directory for the
first `.github`, falling back to the run directory. Printed configuration records
that resolved absolute root. Once started, the server and its tools remain bound
to that root; they do not rediscover a root for each source passed to `extract`.

Tools return compact text, not graph JSON. Read tools operate on extracted graph
contents, so they cannot report code outside the graph. Graph selection defaults
to the first available graph. Pass `graph` from `list_graphs` explicitly when
several graphs exist. Entry arguments and stable entry IDs are also accepted by
the resolver, but returned graph names are the most direct selector.

## `list_graphs`

Arguments: none. Returns one line per graph with name, entry ID, language, node
count, and generation time. With no graphs, returns setup instructions. No writes.

## `search`

| Argument | Default | Meaning |
|---|---|---|
| `query` | required | Case-insensitive substring search |
| `graph` | `""` | Selected graph |
| `kind` | `""` | All categories, or `function`, `type`, `global` |

Returns matching nodes, types, globals, and unresolved targets as text, capped at
60 results with a remaining count. No writes.

## `get_function`

Arguments: required `id`, optional `graph=""`. Accepts a stable ID or an
unambiguous bare/qualified name. Returns a function/module/device record with
signature, directions, referenced types, globals, calls, callers, and annotations.
Ambiguous names return candidates; missing names suggest search or extraction.
No writes.

## `get_net`

Arguments: required `net`, optional `graph=""`, `node=""`, `limit=60` (1–1000).
Returns canonical net alternatives, aliases, guarded terminals and port bindings
present in the selected saved graph. `node` selects a specific occurrence's
binding context. Exact keys win; ambiguous names return candidates. Results are
capped with a remaining count. No extraction or writes occur.

## `netlist_uses`

Arguments: required `target`, `kind` (`definition` or `model`), optional
`graph=""`, `limit=60` (1–1000). Returns declaration status, locations and users,
including unresolved ghosts in the selected graph. It cannot report uses beyond
that graph's extraction boundaries. No writes.

## `callees`

Arguments: required `id`, optional `depth=1`, `graph=""`. Uses the exact node ID
to render outgoing relationships to the requested depth, including edge kind,
signature or unresolved reason. No writes.

## `callers`

Arguments: required `id`, optional `graph=""`. Returns direct incoming edges
present in the graph, including source locations and arguments. It does not run
a new caller search: extract with `include_callers=true` to expand upward first.
No writes.

## `get_type`

Arguments: required `id`, optional `graph=""`. Accepts a type ID or an unambiguous
type name. Returns its fields, layout where available, nested types, enum values,
and users. HDL layout units are bits. No writes.

## `diff_since`

Arguments: optional `since="prev"`, `graph=""`. Returns a compact Markdown
structural diff against the latest snapshot or a supplied timestamp/ISO time.
With no history, returns instructions to create it. No writes.

## `extract`

| Argument | Default | Meaning |
|---|---|---|
| `entry` | required | `file:symbol`, including netlist entries |
| `depth` | `null` | Inherit tracked depth, otherwise use extraction default |
| `include_callers` | `null` | Inherit tracked caller setting |
| `track` | `false` | Persist merged options as a tracked entry |
| `lang` | `null` | Inherit tracked language, otherwise infer it |
| `dialect` | `null` | Inherit netlist dialect, otherwise auto-detect |
| `deck` | `null` | Inherit top deck, otherwise use entry context |
| `search_paths` | `null` | Inherit include search paths |

An omitted or `null` option inherits the existing tracked entry's value, or uses
hx's default if untracked. An explicit value overrides it, including `depth=3`,
`include_callers=false`, and `search_paths=[]`. Here `depth=null` means omitted;
it does not request Python's unlimited-depth behavior.

Writes `.hx/graphs/<slug>.json` even with `track=false`, snapshots an existing
graph before replacement using configured retention, refreshes a matching default
`.hx/graph.json`, and can write frontend caches. New graphs include observed
provenance; previous graphs keep their original bytes and metadata. With `track=true`, also
persists the merged options to config. Options already tracked but not exposed in
this tool's arguments are retained for extraction. Returns a graph summary and
up to 25 node previews. Extraction exceptions are converted into text beginning
`extract failed:`; inspect that text rather than assuming a successful tool call
always produced a graph. Persistence failures begin `save failed:` and indicate
whether the current file committed. `list_graphs` includes available commit
prefixes and modified status.

## `annotate`

MCP initialization uses the project's shared `.hx/annotations.json` and imports
one unambiguous legacy sidecar if needed, preserving the original. Competing or
invalid sources fail startup with stderr diagnostics. Select a legacy source by
copying it to the shared path before startup; no automatic merge is performed.

Arguments: required `id`, optional `note=""`, `tags=""`. `tags` is a
comma-separated string, not a JSON array. Nonempty values replace that field;
empty values leave it untouched. Returns the saved annotation as text, or
`nothing to do` when both are empty. Writes the shared `.hx/annotations.json`
under a file lock.

IDs whose final symbol starts with `struct`, `union`, `enum`, `class`, or `anon@`
are routed to the type bucket; other IDs use the node bucket. For annotation
buckets or deletions beyond this convenience tool, use
[HTTP merge patches](http.md#patch-apiannotations) or the
[Python file API](python.md#annotation-persistence).

## Errors and lifecycle

An unknown graph raises a tool error with a suggestion to call `list_graphs`.
Lookup misses inside several tools return explanatory text. All calls use local
project files; annotation changes are visible to `hx serve` through its file
watcher. Run `hx update` after source changes, or use `extract` for an immediate
new graph.
