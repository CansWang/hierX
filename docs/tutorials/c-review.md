# Review a C/C++ project from an entry point

This walkthrough follows the C fixture's DMA call hierarchy, then reviews a
source edit. Install the [C prerequisites](../getting-started/install.md) and
prepare the project from the checkout:

```bash
python examples/prepare.py c /tmp/hx-c-tutorial
cd /tmp/hx-c-tutorial
```

All subsequent commands run in `/tmp/hx-c-tutorial` with the hx environment active.
The prepared copy has no `.github` marker, so it uses this run directory for
state. In a marked repository, extraction searches upward from the source and
places `.hx` beside the first `.github`; running from `src/` still uses that root.
Use `--root .` to deliberately keep state in a source subdirectory instead.

## Extract and inspect

<!-- hx:test c-extract -->
```bash
hx extract src/main.c:app_run --depth 3
```

The summary names `c:src/main.c::app_run` as the entry and writes
`.hx/graph.json`. The graph contains `dma_start`, its helper `dma_prog_desc`,
macro-wrapped calls to `hal_write32`, and types reached from their signatures.
The unresolved list includes `hal_board_init` (declaration only) and indirect
callback calls. Those records explain a boundary of the graph.

To find the callers of a low-level function, extract upward as well:

<!-- hx:test c-callers -->
```bash
hx extract src/hal.c:hal_write32 --include-callers --depth 2 -o .hx/callers.json
```

Caller nodes have negative depth. This writes a second graph without replacing
`.hx/graph.json`.

Open the first graph:

```bash
hx serve .hx/graph.json --open
```

In the browser, select `dma_start`. Read its signature, globals, and calls.
Follow the `ch` parameter's type into the `dma_chan_t` layout. Click an edge to
see its arguments and source location. Use the depth slider to reduce clutter.

## Keep a review note

In the detail pane, add a note and a tag to `dma_start`. Click the parameter
direction chip to override a heuristic direction when you know more than the
extractor. The **verified** checkbox records the current body hash; after a body
change, the viewer flags that verification as stale.

These edits go to `.hx/annotations.json`, separate from the generated graph.
Refresh the page to see that they persist. Hiding a module with its eye button
also persists in annotations. Stop the server with Ctrl-C when finished.

## Track and change the entry

<!-- hx:test c-track -->
```bash
hx track src/main.c:app_run --depth 3
hx update
```

`track` saves extraction options in `.hx/config.toml`. This `update` replaces the
per-entry current graph created by the earlier CLI extraction and archives that
version. `.hx/graph.json` follows the same entry, so it refreshes too. An entry
with no previous extraction would have no history until its next replacement.

Make a small change to the copied fixture:

<!-- hx:test c-edit -->
```bash
python - <<'EDIT'
from pathlib import Path
import os
p = Path("src/dma.c")
stamp = p.stat().st_mtime_ns + 2_000_000_000
old = p.read_text()
assert "    g_dma_active++;" in old
p.write_text(old.replace("    g_dma_active++;", "    g_dma_active += 2;"))
os.utime(p, ns=(stamp, stamp))
EDIT
hx update
hx diff --entry src/main.c:app_run
```

The diff reports a body change to `dma_start`. The previous graph is now in
`.hx/history/`, and `.hx/last-diff.md` contains the latest update report.
Whitespace and comments alone do not change a token-based body hash.

Run `hx serve --open` to use the tracked-graph picker and **diff** selector.
Choose the previous snapshot to highlight changed nodes. The **baseline** button
creates a snapshot without re-extracting.

For ongoing work:

```bash
hx watch
```

The watcher polls source files and updates tracked entries after a quiet period.
Stop it with Ctrl-C. `hx watch --once` performs a single update and exits.

## Share a graph

Export the caller graph, whose annotations share the same stable IDs:

<!-- hx:test c-export -->
```bash
hx export .hx/callers.json -o .hx/review.html
```

Open `.hx/review.html` in a browser. It includes the graph, annotations, and viewer
assets. It supports inspection, but has no server to persist edits or re-extract.

Continue with the [C/C++ guide](../guides/c-cpp.md),
[configuration reference](../reference/configuration.md), or
[diff reference](../reference/diff.md).
