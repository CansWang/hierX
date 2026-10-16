# Give an agent access to hx graphs

This walkthrough uses the [prepared netlist project](netlists.md). Run commands
from that workspace in the activated hx environment.

## Create a graph and configure MCP

<!-- hx:test agents-prepare -->
```bash
hx track ota.sp:. --dialect ngspice --depth 2
hx update
hx mcp --print-config
```

The last command prints an `mcpServers` configuration containing the hx executable,
`mcp` arguments, and the absolute project root. Add it to your MCP client's server
configuration. If the executable is named only `hx`, use the absolute executable
from the activated environment when the client does not inherit your PATH.

`hx mcp --root /absolute/project/path` starts the stdio server. Let the client
start it; its standard streams carry the protocol.

## Query, then inspect

Call the tools in this order through the client:

```json
{"name": "list_graphs", "arguments": {}}
```

Copy a returned graph name into subsequent calls, especially when several entries
are tracked:

```json
{"name": "search", "arguments": {"query": "m_load_1", "graph": "RETURNED_GRAPH_NAME"}}
```

Use the stable ID from the search result with `get_function`. Despite its name,
that tool also returns module and device records. On call graphs, `callees` and
`callers` show the recorded edges; `callers` can only report callers present in
the extracted graph.

## Extract and annotate through tools

```json
{"name": "extract", "arguments": {"entry": "ota.sp:xa", "depth": 2, "dialect": "ngspice", "track": true}}
```

This writes a graph and persists the merged extraction options. For already
tracked entries, omitted or `null` options inherit the tracked values. Explicit
`false`, `3`, or `[]` override them. `track: false` still writes the graph but does
not add a tracked entry.

```json
{"name": "annotate", "arguments": {"id": "sp:ota.sp::xa", "note": "Reviewed input branch", "tags": "reviewed,analog"}}
```

The note is shared with the viewer. Empty annotation arguments leave existing
values untouched; remove notes through the viewer or HTTP merge patch API.
After a source edit and `hx update`, use `diff_since` to read the changes since
the previous snapshot. See the [tool reference](../reference/mcp.md) for arguments
and responses.

## Update graphs after an editing session

Run `hx watch` in another terminal for a polling loop, or invoke `hx update` at
the end of a session. For a Claude Code hook, preview the configuration first:

```bash
hx hook print
```

`hx hook install` merges the hook into `.claude/settings.json` in the project.
Use `--settings-dir` to choose another settings directory. The default `Stop`
hook runs `hx update --quiet --hook`; `--event PostToolUse` uses the edit-tool
matcher instead. Hook mode reads stdin and exits successfully even if an entry
fails, so consult `.hx/last-diff.md` for errors.
