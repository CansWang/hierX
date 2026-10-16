# Learn to use hx

hx extracts the structure reachable from an entry point into a JSON graph. Use
that graph to understand a call or instance hierarchy, review a code change, and
keep notes attached to stable symbol IDs.

Start with [installation](getting-started/install.md) and
[preparing the example projects](getting-started/examples.md), then choose a path:

| Your goal | Start here |
|---|---|
| Review C/C++ functions, types, and changes | [C/C++ review tutorial](tutorials/c-review.md) |
| Explore a circuit without installing a simulator | [Netlist quickstart](tutorials/netlists.md) |
| Automate extraction and comparisons | [Python scripting tutorial](tutorials/python-api.md) |
| Give an agent access to your graphs | [Agent integration](tutorials/agents.md) |
| Use an HDL or language-server frontend | [SystemVerilog](guides/systemverilog.md), [Rust](guides/rust.md), [Python](guides/python.md) |

## Understand the workflow

1. **Extract** from `file:symbol`. Choose a root and a depth to bound the graph.
2. **Inspect** the hierarchy in `hx serve`, follow edges, and read node details.
3. **Annotate** with notes, direction overrides, tags, and verification marks.
4. **Track** important entries, **update** after an edit, and **diff** against history.
5. **Share** a standalone HTML export or consume the graph through an API.

The generated graph and human annotations are separate files. Re-extraction
replaces the graph; annotations remain keyed by symbol ID.

## Find an exact contract

Use the [CLI reference](reference/cli.md) for command syntax,
[Python reference](reference/python.md) for scripting,
[graph format](reference/graph.md) for JSON consumers,
[HTTP reference](reference/http.md) for the viewer server, and
[MCP reference](reference/mcp.md) for agent tools.

The language guides explain precision and limitations. A graph can contain
unresolved targets or diagnostics even when extraction succeeds; see
[troubleshooting](troubleshooting.md) before treating missing data as missing code.
