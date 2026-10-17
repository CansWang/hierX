# Explore a netlist without a simulator

The native parser extracts SPICE/ngspice structure without running a simulator.
Prepare the five-transistor OTA fixture from the checkout:

```bash
python examples/prepare.py netlist /tmp/hx-netlist-tutorial
cd /tmp/hx-netlist-tutorial
```

All commands below run in that copied workspace with hx installed.

## Extract a deck

<!-- hx:test netlist-extract -->
```bash
hx extract ota.sp:. --dialect ngspice --depth 2
```

`.` selects the whole deck. The summary reports files parsed or cached and
counts diagnostics. `.hx/graph.json` contains the deck, subcircuit instances
`XA` and `XB`, devices, and a `circuit` section with nets, terminals, definitions,
models, parameters, and diagnostics.

```bash
hx serve --open
```

Select an instance and inspect its ports and connections. Device terminal
bindings are available in the detail pane. Case-insensitive lookup uses
case-folded IDs while names retain their source spelling.

Use the Nets, Definitions and Models selector to navigate circuit records.
Selecting a terminal's net highlights its connected devices and hierarchy paths.
Hidden/depth-filtered devices stay hidden; the detail panel reports endpoints
outside the current view. These features also work in standalone exports.

Saved graphs support read-only queries:

```bash
hx netlist net out --graph .hx/graph.json
hx netlist uses /five_t_opamp --kind definition --graph .hx/graph.json --json
```

Queries list only what was extracted. Guarded bindings remain alternatives; use
`net --node ID` to choose an occurrence's context. MCP provides `get_net` and
`netlist_uses`. Circuit diff mode adds separate wiring, model, definition and
parameter changes, including before/after records for removed declarations.
Legacy graphs without occurrence guard constraints report that they need
re-extraction before contextual queries can filter conditional alternatives.

## Xyce

Use `hx extract deck.cir:. --dialect xyce --all` for native Xyce structure.
Named devices retain their type in IDs, such as `yadc!probe`. Device grammar
metadata is pinned to Xyce 7.10; model expressions stay symbolic.

```bash
hx netlist check deck.cir:. --oracle xyce --json
hx netlist check deck.cir:. --oracle xdm --json
```

Xyce checks original-deck syntax/topology, family counts (accounting for coupled
inductor grouping), and exposed net names. XDM checks its top-level primitive
inventory; it does not expose subcircuit inventory or terminal bindings through
that interface. Warnings indicating translation loss return unavailable, even
when XDM exits successfully. Neither check claims full terminal-level simulator
agreement. Original sources are mirrored without overwriting them. The explicit
production runner requires both local tools:

```bash
python dev/scripts/hardening_coverage.py --suite xyce --out /tmp/hx-xyce-coverage
```

## Narrow the graph

<!-- hx:test netlist-entries -->
```bash
hx extract ota.sp:xa.m_load_1 --include-callers -o .hx/device.json
hx extract ota.sp:@five_t_opamp -o .hx/definition.json
hx extract lib/devices.inc:@nch_wrap --deck ota.sp -o .hx/library.json
```

The first entry focuses on one occurrence and includes its parents. The second
roots the view at a definition, making it reusable across decks. The third names
the file defining a library subcircuit while `--deck` supplies deck context.
Use repeated `--search-path DIR` options when includes live outside the deck's
normal resolution paths.

Expressions remain symbolic. Model families are resolved, but a W/L bin is not
selected. Conditional occurrences carry guards rather than choosing a branch.
The stored `.control` block is never executed during extraction.

## Track and export

<!-- hx:test netlist-track -->
```bash
hx track ota.sp:. --dialect ngspice --depth 2
hx update
hx watch --once
hx export .hx/graph.json -o .hx/review.html
```

Tracked options are reused by updates and the MCP extractor. Watch dependencies
include library files and missing include candidates, so adding an include can
trigger a later update.

## Try repository-root discovery

The prepared copy has no `.github` marker. Add one in this disposable workspace
and try extraction and export from a nested run directory:

<!-- hx:test netlist-discovery -->
```bash
mkdir .github
mkdir review
cd review
hx extract ../ota.sp:. --dialect ngspice --depth 2
hx export -o review.html
```

Extraction finds the marker above `ota.sp` and writes the workspace root's
`.hx/graph.json`. Export finds no `review/.hx`, so it searches upward to the same
marker and reads that graph. The HTML output is invocation-relative:
`review/review.html`. Return to the workspace root with `cd ..` before the next
section. See [configuration](../reference/configuration.md) for nested-repository
boundaries and empty local state.

## Optional: compare with ngspice

With `ngspice` installed, use the fixture's unconditional oracle deck:

<!-- hx:test netlist-oracle -->
```bash
hx netlist check ota_oracle.sp:. --oracle ngspice
```

The check compares unguarded device paths, terminal counts, nets, models, and
controlling references. It strips control blocks before invoking ngspice.
Exit status is 0 for agreement, 1 for mismatches, and 2 for an unavailable oracle.
Symbolic parameters or missing model implementations can make a deck unavailable
even when native extraction succeeds. Add `--json` for the full comparison report,
including the rendered closure passed to the oracle.

See the [graph reference](../reference/graph.md#netlist-circuit-data) for the
circuit data and [troubleshooting](../troubleshooting.md#netlists) for diagnostics.
