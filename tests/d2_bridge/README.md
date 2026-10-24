# D2 architecture examples from real repositories

Run these examples directly from this directory. They use Hx's implemented D2
interpretation layer and native ELK boundary ports, with **working links from
every block and port to pinned source code**.

Measured results and practical limitations are recorded in [FINDINGS.md](FINDINGS.md).

These are authored architecture sketches. Their arrows describe a chosen view
of data flow; they are not extracted call edges, execution traces, type checks,
or architecture conformance results. The bundled source files are repository
slices for reading, not complete applications that can be built independently.

## First run

From the repository root, install the Python dependencies once if needed:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,e2e]'
```

Then work in this directory:

```bash
cd tests/d2_bridge
./run.sh setup
./run.sh list
./run.sh check all
./run.sh gallery --open
```

Open **<http://127.0.0.1:8766/examples>** if the browser does not open
automatically. The terminal runs one foreground server. Leave it running while
using the diagrams and source links; stop it with **Ctrl+C**.

`setup` delegates to `dev/scripts/setup_d2_bridge.sh`. The thin Go bridge calls
the unmodified upstream D2 v0.9.0 compiler. If compatible Go is absent, explicit
setup downloads and verifies Go 1.27.3 and installs it under your user account.
It does not change system Go or shell profiles. Setup may need network access
for Go and module downloads. Inspecting, serving, exporting and checking examples
never download tools or build Codex/FFmpeg.

```bash
# Reuse an installed SDK and prohibit SDK downloading:
./run.sh setup -- --no-bootstrap

# Optional custom SDK location (the helper still uses its normal destination):
./run.sh setup -- --go-dir "$HOME/.local/lib/go1.27.3"
```

The default bridge location is `~/.cache/hx/tools/bin/hx-d2-bridge`. Hx discovers
it automatically. For an explicit executable:

```bash
./run.sh --d2-bridge /absolute/path/to/hx-d2-bridge check all
# Or set HX_TOOL_D2_BRIDGE for the commands below.
```

The wrapper chooses `PYTHON` when set, otherwise the repository's `.venv/bin/python`,
otherwise `python3`. Use an environment that has this checkout's dependencies:

```bash
PYTHON=/absolute/path/to/venv/bin/python ./run.sh list
```

Paths are anchored to the wrapper, so commands also work from another directory:

```bash
/absolute/path/to/hierX/tests/d2_bridge/run.sh serve codex-paths --port 8770
```

## What to try in the viewer

Blue pins are inputs and orange pins are outputs. Solid arrows connect sibling
blocks. Dashed arrows expose an enclosing block's port through a child port.

- Click a **block title** to open its owning declaration in a new source-viewer tab.
- Click a **boundary pin or port label** to open that port's explicitly linked
  declaration. A port can link to a different API than its block.
- Click an arrow or a block outline to inspect its authored identity and details.
- Scroll over the diagram to zoom, drag empty space to pan, and click **fit** to reset.
- Open a diagram on its own for more room. The gallery's embedded previews use
  the same renderer and links.

The FFmpeg pipelines are horizontally wide. A fit view shows their overall
composition with small labels; zoom in to read and click individual APIs, then
pan along the pipeline. Geometry checks measure SVG coordinates in both fitted
and actual-size views; they do not claim that every label remains readable in a
reduced gallery thumbnail.

Source navigation opens the declaration, signature and source range. It does not
highlight an individual argument or return token. Source-viewer extraction is
disabled. Its ordinary annotations/history live under `.generated/`, separately
from the pinned sources and authored D2.

## Testcases

| Case | Blocks / ports / arrows | Main visual features |
|---|---:|---|
| `codex-paths` | 5 / 12 / 6 | Nested resolver, multiple inputs, separate normalization instances |
| `codex-search` | 5 / 18 / 11 | Nested workers, asynchronous result flow, reverse connection |
| `ffmpeg-transcode` | 5 / 13 / 4 | Packet/frame pipeline, API-specific input/output links, unconnected status ports |
| `ffmpeg-av-reuse` | 10 / 23 / 12 | Imported reuse, nested exposures, parallel branches and convergence |
| `hx-review` | 7 / 16 / 9 | Nested frontend/traversal, graph persistence and saved-path fan-out |

### Codex: resolving a path

```bash
./run.sh inspect codex-paths
./run.sh serve codex-paths --open
```

Edit [cases/codex-paths/main.d2](cases/codex-paths/main.d2).
The enclosing resolver exposes `path`, `base` and `resolved`. Inside it, home
expansion feeds path normalization, while base normalization is a separate
instance. Both reach `Absolutize`, whose result reaches the enclosing output.

Click **Resolve path against base**, then **Normalize path** and **Normalize base**.
The first opens `AbsolutePathBuf::resolve_path_against_base`; the last two open
the same `normalize_path_for_platform` declaration while retaining distinct
diagram identities. This illustrates a conceptual processing view; platform
conditions remain in the Rust implementation.

### Codex: asynchronous file search

```bash
./run.sh inspect codex-search
./run.sh serve codex-search --open
```

Edit [cases/codex-search/main.d2](cases/codex-search/main.d2).
The session contains one filesystem walker and one incremental matcher. Query
and root inputs are exposed inward; matches and completion are exposed outward.
The reporter returns results to the caller through an ordinary opposite-flow
connection. Separate scalar arrows express these directions; there is no bundle.

Click the session's query pin to open `FileSearchSession::update_query`, then
the walker and matcher titles to inspect their worker functions. The completion
port links to `SessionReporter::on_complete`. Worker scheduling and callbacks
remain implementation details, rather than obligations checked by this sketch.

### FFmpeg: packet/frame pipeline

```bash
./run.sh inspect ffmpeg-transcode
./run.sh serve ffmpeg-transcode --open
```

Edit [cases/ffmpeg-transcode/main.d2](cases/ffmpeg-transcode/main.d2).
Follow demux → decode → filter → encode → mux. Packets and frames use separately
named ports. Status outputs are intentionally unconnected, which is supported.

Click the decoder input and output pins: they open `avcodec_send_packet` and
`avcodec_receive_frame`, respectively. Click the encoder output to open
`avcodec_receive_packet`. This demonstrates distinct API bindings on one block.
The diagram abstracts buffering, retries, flushing, stream configuration and
error handling; it does not claim each input immediately produces an output.

### FFmpeg: reused audio and video paths

```bash
./run.sh inspect ffmpeg-av-reuse
./run.sh serve ffmpeg-av-reuse --open
```

Edit [cases/ffmpeg-av-reuse/main.d2](cases/ffmpeg-av-reuse/main.d2) and its imported
[codec-chain.d2](cases/shared/codec-chain.d2).
`audio` and `video` instantiate the same decode/filter/encode definition. Each
exposes child ports at its boundary; both branches converge at the muxer.

Click matching pins in both branches: they open the same FFmpeg API, although
their diagram paths begin with `audio.` and `video.`. This is an illustrative
two-stream composition using real APIs, not a traced FFmpeg command invocation.

### Hx: extraction, persistence and review

```bash
./run.sh inspect hx-review
./run.sh serve hx-review --open
```

Edit [cases/hx-review/main.d2](cases/hx-review/main.d2).
The extractor contains frontend construction and bounded traversal. Its graph
feeds persistence; the saved path fans out to graph loading and HTML export.
Click these blocks to inspect `make_frontend`, `extract_graph`,
`save_extraction`, `load_graph_dict` and `export_file`.

This uses committed extraction foundations, rather than a snapshot of the
uncommitted D2 implementation. It is a selected architecture view, not an
exhaustive account of every function parameter or dependency.

## Edit, inspect and compare

Keep the gallery running, change a case's D2, and **reload that case's page**.
Imports are recompiled on reload too. The files under `cases/` remain the primary
authored input. Invalid D2 produces diagnostics instead of retaining an old diagram.

```bash
./run.sh inspect codex-search --json
./run.sh check all
```

`inspect --json` prints the derived architecture documents. The checked-in
`examples.json` holds independent expected blocks, parents, port directions,
code targets and connections for regression checks. Deliberately changing the
topology requires reviewing those expectations; changing only display labels
does not require updating node/port identities. Connection labels are checked.

Inputs use the current Hx D2 profile: `hx-input`, `hx-output`, `->`,
`hx-exposure` and exact `hx:` links. Descriptive labels such as `AVPacket` or
`Vec` do not introduce width/type semantics. Buses, bundles, compatibility checks
and behavioral validation remain deferred. D2 shape/style/layout attributes
are ignored with diagnostics; Hx/ELK controls presentation.

## Export a local gallery

```bash
./run.sh export all
# Open .generated/exports/index.html in your browser.
```

Each case HTML embeds its diagram model and runtime assets. The index embeds
those pages as previews. Diagrams work without a server or external requests.
**Default offline exports have disabled code links**, because source bodies are
not embedded.

For exported diagrams with working code navigation, keep a gallery server running
and explicitly supply that server's source-viewer base URL:

```bash
# Terminal 1:
./run.sh gallery --port 8770

# Terminal 2, also in tests/d2_bridge:
./run.sh export all --code-url http://127.0.0.1:8770/
```

Then open `.generated/exports/index.html`. The URL must point at the viewer with
these examples' navigation catalog, not an unrelated Hx graph. Stop the server
and those code links stop working; the diagrams remain interactive.

## Browser measurements and screenshots

Install Chromium once in the same Python environment used by the wrapper:

```bash
../../.venv/bin/python -m playwright install chromium
./run.sh check all --browser
```

The browser check runs three layouts of every case at 100% and 150% CSS zoom:
30 layout/zoom combinations, measured both fitted and at actual SVG scale
(**60 measured views**), and **684 actual block/port clicks** for all five cases.
It checks measured SVG pin placement, arrow endpoints, labels, clipping and
routes through unrelated blocks. Actual click targets must open the exact
signature, source filename/line and pinned source text. Missing Chromium is an
error when `--browser` is requested; it is not reported as a passing check.

Outputs:

| Path under `.generated/` | Contents |
|---|---|
| `.hx/graph.json` | Locally rebased navigation catalog; no extracted relationships |
| `reports/check.json` | Source, topology and code-binding checks |
| `reports/browser.json` | Tool/input hashes, measured geometry, clicks and failures |
| `browser/*.png` | Fit-to-window captures of the first layout at both zooms |
| `browser/*.svg` | Original first-layout DOM SVG captures for debugging; styles live in the diagram HTML |
| `browser/*-layout.json` | First-layout geometry for investigation |
| `exports/index.html` | Generated HTML gallery |
| `exports/<case>.html` | Standalone interactive diagrams |

All generated outputs are ignored by Git. Re-running a command replaces its own
outputs. To reclaim the large visual outputs while preserving small reports:

```bash
rm -rf -- .generated/exports .generated/browser
```

Keep `.generated/reports/` when recording findings. Do not delete the historical
reports under `~/hx-review-artifacts`; this harness does not modify them.

## Source provenance and fresh extraction

[sources/manifest.json](sources/manifest.json) lists each file's original path,
repository revision and SHA-256. Original source headers and root license/notice
files are preserved. In Codex, snapshot paths below `sources/codex/` correspond
to upstream `codex-rs/`. FFmpeg and Hx retain their upstream root-relative paths.

| Repository | Pinned revision |
|---|---|
| [OpenAI Codex](https://github.com/openai/codex) | `221e4e7c05386d06aa7b91da2a9b04f7f2bd921f` |
| [FFmpeg](https://github.com/FFmpeg/FFmpeg) | `ba987fe24d6713c4d4b3a15cebaeca18c41fbd31` |
| [Hx](https://github.com/CansWang/hierX) | `2e54a843138830df4afce07474567f1a8bbfff0e` |

[navigation.json](navigation.json) retains selected real declaration metadata:
Codex's saved Rust acceptance records and declarations obtained through the
existing libclang and Pyright frontends. It records original IDs and metadata
origins. Compiler/LSP precision describes the original declarations, not the
authored diagrams. Relationships, global/type expansion and body hashes are
omitted. Runtime preparation rebases IDs/locations under the common source root
and creates a navigation-only catalog; it does not synthesize cross-repository
call edges or claim complete extraction provenance. Most declarations have no
entry-tree path; use the source viewer's search to browse the catalog directly.

The previews need neither Cargo/rust-analyzer nor FFmpeg compiler configuration.
To independently re-extract an upstream entry, use a **full checkout at the pin**,
not these source slices. Examples with placeholder absolute paths:

```bash
# Codex: set up its pinned Rust toolchain and rust-analyzer first.
# Previous acceptance used Rust/rust-analyzer 1.95.0; indexing may be expensive.
hx extract 'file-search/src/lib.rs:create_session' \
  --root /absolute/path/to/codex/codex-rs --depth 0 \
  -o /tmp/codex-create-session.json

# FFmpeg: configure the full checkout and generate a real compilation database.
# Pass the database directory containing compile_commands.json.
hx extract 'libavcodec/decode.c:avcodec_send_packet' \
  --root /absolute/path/to/FFmpeg \
  --compile-commands /absolute/path/to/FFmpeg-build --depth 0 \
  -o /tmp/ffmpeg-send-packet.json

# Hx: use an isolated checkout at the baseline and its Pyright environment.
hx extract 'hx/api.py:extract' --root /absolute/path/to/hierX-baseline \
  --depth 0 -o /tmp/hx-extract.json
```

These optional commands produce ordinary observed extraction graphs. They do not
automatically replace the pinned navigation catalog or validate the sketches.
For any intentional snapshot update, verify the source revision and declaration
ranges, retain licenses, update hashes and expectations, and rerun both checks.

## Troubleshooting

- **Bridge absent or wrong version:** run `./run.sh setup`; verify an explicit
  `HX_TOOL_D2_BRIDGE` does not point to an old helper. See the repository README
  for Go bootstrap details.
- **Python import/dependency error:** select the repository virtualenv with
  `PYTHON`, or install the dependencies from the first-run instructions.
- **Port in use:** add `--port 8770` to `serve` or `gallery`. Source links use the
  running server's actual URL.
- **Snapshot hash mismatch:** restore the named pinned source file. Editing
  `cases/*.d2` requires no edits to the source snapshots.
- **Unresolved binding or changed topology:** run `inspect <case> --json` and
  examine `.generated/reports/check.json`. Every block and port needs its own
  exact link; bindings do not inherit from parents.
- **Source link unavailable in an export:** restart the matching live gallery
  and re-export with `--code-url`; offline HTML deliberately contains no sources.
- **Layout check fails:** inspect `reports/browser.json` and the captured PNG/SVG.
  A failure is retained as a failure, rather than silently skipping the testcase.
