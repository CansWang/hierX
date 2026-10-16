# HTTP API and live events

Start the local viewer with `hx serve`. The default base URL is
`http://127.0.0.1:8765`. Endpoints expose the same graph and annotation files used
by the viewer. There is no authentication layer; use the default loopback binding
for local work. Serve with `--no-extract` to disable server-triggered extraction.

With no graph argument, CLI startup follows the
[local-first state lookup](configuration.md#find-a-graph-for-serve-or-export).
`serve --root` changes the source-lookup root, not which graph is served.

Graph-specific endpoints accept an optional `name` query parameter from
`GET /api/graphs`. Omit it for the server's primary graph. An unknown name returns
404. Annotations are shared across the server's graphs and do not take `name`.
Normal JSON error responses use FastAPI's `{"detail": ...}` shape; parameter
validation can return 422. `POST /api/extract` has its own 409 response below.

## `GET /api/status`

Optional query: `name`. Returns `graph_path`, `annotations_path`, `root`, `entry`,
`generated`, `schema`, a compact `provenance` summary, migration status/detail, annotation `rev`, `extracting`,
`allow_extract`, `last_extract_error`, and available graph names. Some graph
metadata is null when a primary graph is unavailable.

```bash
curl http://127.0.0.1:8765/api/status
```

## `GET /api/graphs`

Returns an array of available graph descriptors with `name`, `entry`, `entry_arg`,
`lang`, `generated`, node count `nodes`, compact `provenance`, and migration status. Invalid graph files
are omitted from the list. Copy the returned `name` to select a tracked graph.

## `GET /api/graph`

Optional query: `name`. Returns the normalized graph document directly, including
in-memory upgrades of supported older schemas and lossless wide values. Missing
graph files return 404; malformed graph documents return 500.

```bash
curl --get http://127.0.0.1:8765/api/graph --data-urlencode name=graph
```

`graph` names the default `.hx/graph.json` when that is the primary file. For
other filenames, first discover the name through `/api/graphs`.

## `GET /api/history`

Optional query: `name`. Returns `{"entry": "...", "snapshots": [...]}`. Each
snapshot has opaque identifier `ts`, `path`, `generated`, and compact `provenance`
values (null for older graphs). Full input manifests stay in graph metadata. An empty array means there is
no baseline/history yet.

## `POST /api/snapshot`

Optional query: `name`; no body. Copies the selected current graph into history,
using the project's retention setting. Identical baselines reuse the saved file.
Returns `entry`, a `snapshot` identifier
(or null if no snapshot was created), and the updated `snapshots` array.

```bash
curl -X POST http://127.0.0.1:8765/api/snapshot
```

## `GET /api/diff`

Optional queries: `name`, `since=prev`, `format=json`. Compares the current selected
graph with the chosen history point. `since` accepts a snapshot identifier or ISO
time as described in the [diff reference](diff.md). Returns the diff with `since`,
`since_generated`, and `markdown` fields; `format=md` returns plain Markdown text. Invalid
history identifiers return 400. No history yields
404 with a suggestion to take a baseline.

```bash
curl --get http://127.0.0.1:8765/api/diff --data-urlencode since=prev --data-urlencode format=md
```

## `GET /api/annotations`

Returns `{"rev": 0, "annotations": {...}}`. `rev` is the running server's
annotation revision, not a graph revision or write precondition. Malformed
annotation JSON returns 500. The [annotation document](annotations.md) has schema
`hx-ann/1`.

## `PUT /api/annotations`

Body: the replacement annotation document itself. Replaces and normalizes it,
increments the revision, and broadcasts an `annotations` event. Returns the same
wrapper as GET. Missing buckets are initialized; a non-object body normalizes to
an empty annotation document. Use PATCH to preserve unrelated notes.

## `PATCH /api/annotations`

Body: a JSON object merge patch. Objects merge recursively; arrays replace;
`null` deletes keys. Writes are locked and persisted atomically. Returns
`{"rev": N, "annotations": {...}}` and broadcasts `annotations`. A non-object
patch returns 400.

For the prepared C fixture:

```bash
curl -X PATCH http://127.0.0.1:8765/api/annotations \
  -H 'Content-Type: application/json' \
  -d '{"nodes":{"c:src/dma.c::dma_start":{"note":"Reviewed","tags":["dma"]}}}'
curl -X PATCH http://127.0.0.1:8765/api/annotations \
  -H 'Content-Type: application/json' \
  -d '{"nodes":{"c:src/dma.c::dma_start":{"note":null}}}'
```

The second request deletes only the note, retaining the tag. Do not send the GET
response wrapper as the patch body.

## `GET /api/source`

Required query: `file`. Optional: `line=1`, `span=40`, `name`. Returns
`{"file": "src/dma.c", "start": 1, "lines": ["..."]}`. The span is clamped to
1–400 lines. The effective project root comes from `--root` or the selected graph.
Absolute paths are accepted only inside that root, with symlinks resolved.
Returns 400 when no root is known, 403 for paths outside it, and 404 for missing
files.

```bash
curl --get http://127.0.0.1:8765/api/source \
  --data-urlencode file=src/dma.c --data-urlencode line=1 --data-urlencode span=8
```

## `POST /api/extract`

Optional query: `name`; no extraction-options body. Replays the selected graph's
`meta.extract_args` in the background and snapshots the previous graph after
successful extraction. Returns 202 with `{"status": "started"}`. Returns 403
when extraction is disabled, 409 with `{"status": "already-running"}` if another
extraction is running, and 400 when replay arguments are absent.

Managed current files use the shared save mechanism and refresh a matching
`.hx/graph.json` copy. Standalone files are saved back to their selected path.
Historical files are immutable and cannot be re-extracted in place. New graph
provenance describes the new run; the archived graph retains its previous metadata.

Use `/api/status` or SSE to observe completion; 202 acknowledges startup rather
than success. A later failure is reported in `last_extract_error` and an
`extract-error` event.

## `GET /events`

Streams Server-Sent Events with `Content-Type: text/event-stream`. The stream is
shared across served graphs; inspect payload `name` where present. There is no
replay history or `Last-Event-ID` recovery. Reload current state after reconnect.

```bash
curl -N http://127.0.0.1:8765/events
```

| Event | JSON data |
|---|---|
| `hello` | Current annotation `rev` when connecting |
| `ping` | Keepalive timestamp `t`, normally after 15 idle seconds |
| `graph` | `reason` (`file-changed` or `extract`) and graph `name` |
| `annotations` | `rev`, optionally `reason: file-changed` |
| `extract-start` | Entry argument `entry` and optional graph `name` |
| `extract-done` | Stable entry ID `entry`, node count `nodes`, and graph `name` |
| `extract-error` | Error message `error` |

A graph notification tells clients to fetch the current graph; it does not embed
the graph. Annotation notifications similarly trigger a fresh annotation request.
