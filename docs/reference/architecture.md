# D2 architecture sketches

Architecture sketches describe authored blocks, individual input/output ports,
and connections. They use upstream D2 syntax with Hx interpretation and direct
ELK layout. They are separate from extracted `hx/4` graphs and human annotations.
Arrows describe intended data/signal flow, not observed execution or conformance.

## Install the optional parser bridge

From a checkout with Python 3.10 or newer, run:

```bash
bash dev/scripts/setup_d2_bridge.sh
```

Setup uses a working Go 1.27+ from PATH or the local SDK directory. When Go is
missing or older, it downloads pinned [Go 1.27.3](https://go.dev/dl/#go1.27.3),
verifies its published SHA-256, and installs it under `~/.local/lib/go1.27.3`.
Automatic SDK installation supports Linux/macOS amd64/arm64. The SDK is retained;
system Go and shell configuration are unchanged. To use it interactively:

```bash
export PATH="$HOME/.local/lib/go1.27.3/bin:$PATH"
go version
```

Use `--go-dir DIR` to change the fallback SDK directory, or `--no-bootstrap` to
require an existing compatible compiler. The latter disables SDK downloading;
Go modules may still need downloading during the build. For example:

```bash
bash dev/scripts/setup_d2_bridge.sh --no-bootstrap
bash dev/scripts/setup_d2_bridge.sh --go-dir "$HOME/tools/go1.27.3"
```

Setup builds `hx-d2-bridge` into `~/.cache/hx/tools/bin/`. It pins D2 v0.9.0 and
module checksums. An optional positional argument selects another executable
output path. The build replaces an existing helper only after compilation and
version verification succeed. Go is needed to build the helper, not to run Hx
afterward. Normal Hx
installation/extraction does not require it; architecture commands never fetch
or build tools automatically. Tool lookup is `--d2-bridge PATH`,
`HX_TOOL_D2_BRIDGE`, PATH, then the default cache location. A wrong explicit path
does not fall back. Missing tools and incompatible bridge versions are errors.

The bridge is Go so it can call D2's upstream Go compiler directly. Hx's
interpretation stays in Python and its layout/presentation stays in JavaScript.
The adapter preserves upstream import/class/key handling without a parser rewrite
or compiler fork.

## Write and preview a sketch

Save this as `design.d2`:

```d2
producer: Producer {
  seed: u32 {class: hx-input}
  sample: u32 {class: hx-output}
}
consumer: Consumer {
  sample: u32 {class: hx-input}
}
producer.sample -> consumer.sample: sample
```

```bash
hx arch inspect design.d2
hx arch inspect design.d2 --json
hx arch serve design.d2 --open
hx arch export design.d2 -o design.html
```

Ordinary D2 objects become blocks; `hx-block` is an optional explicit marker.
Ports are immediate child objects marked `hx-input` or `hx-output`. Class
definitions are not required for these markers. Port labels and types are
descriptive text: Hx performs no type compatibility or required-connection check.
Unconnected ports are allowed. Each `->` wire joins a sibling block's output to
another sibling's input. Reverse-flow scalar wires are supported independently.

The preview provides fit, wheel zoom, drag pan, selection details and optional
code navigation. Refresh the browser to recompile edited D2 and imported files;
there is no automatic architecture watcher or browser authoring UI. Invalid
refreshes display diagnostics and clear the diagram instead of showing stale
intent as current. The underlying code viewer keeps its normal annotation
behavior; re-extraction is disabled in this preview.

## Nested exposure and reuse

```d2
pipeline: Pipeline {
  seed: u32 {class: hx-input}
  result: u32 {class: hx-output}
  worker: Worker {
    seed: u32 {class: hx-input}
    result: u32 {class: hx-output}
  }
  seed -> worker.seed: input {class: hx-exposure}
  worker.result -> result: output {class: hx-exposure}
}
```

Exposure edges are explicit: parent input → child input, or child output →
parent output. Other cross-level connections must use these boundaries. This
checks endpoint roles and containment, not architectural obligations.

Upstream local imports work, including `first: @worker` and `second: @worker`.
Their instances retain separate qualified identities even when they share a
definition or code target. Quoted D2 keys keep their segment boundaries; Hx does
not split quoted names on dots. Imports are confined to the selected project
root, including symlinks. The default root is the design's directory; use
`--root PROJECT` when designs import files elsewhere inside that project.

## Code navigation and HTML export

Use the normal D2 `link` attribute with an exact saved node ID:

```d2
producer: Producer {
  link: "hx:rs:src/lib.rs::produce"
  sample: u32 {class: hx-output; link: "hx:rs:src/lib.rs::produce"}
}
```

```bash
hx arch serve design.d2 --graph graph.json --open
hx arch export design.d2 --graph graph.json --code-url http://127.0.0.1:8765/ -o design.html
```

`--graph` supplies exactly one saved extraction graph. Code links open the
owning function/declaration in the existing viewer, including its signature and
available source. There is no symbol guessing, ownership projection, automatic
extraction, parameter-token highlighting or runtime dataflow inference. Repeated
links to one symbol do not merge diagram instances. Missing symbols and omitted
graphs leave explicit unresolved-link warnings and no active code link.

HTML exports embed the interpreted document, renderer, ELK runtime and its
license. Rendering works offline. Source text is not embedded; active exported
code links require both a resolved graph binding and an explicit HTTP(S) viewer
URL without a fragment. Keep that viewer serving the matching graph. Without
the URL, code navigation is visibly unavailable. Export refuses to overwrite
its D2/import/graph inputs, including symlink or hardlink aliases.

## Derived data, limits and future extensions

`hx arch inspect --json` returns `hx-arch/1`: blocks, ports, connections,
navigation bindings, diagnostics, source ranges, hashes of compiled D2/import
bytes, and the optional saved graph hash. The packaged schema is
`hx/schema/hx-arch-1.schema.json`. This is derived output, not another authoring
format or an extension of extraction graphs. Source range lines/columns are
one-based with an exclusive end; diagnostics may provide only the start.
Layout coordinates are separate.

Hx supports the ordinary-port architecture profile, not the full D2 renderer.
It owns rectangular blocks, visible boundary pins, layout and theme. D2 shape,
size, styling and layout attributes are reported as ignored; D2 layers, steps
and scenarios are unsupported. Invalid roles/endpoints and unsupported Hx markers
are errors. Helper/graph/I/O failures return exit 2; invalid D2/profile designs
return 1; unresolved code links are warnings. No partial design is presented as
valid.

Parser adaptation, interpretation, navigation resolution, layout and SVG
presentation are separate internal stages. Future bus/bundle normalization can
extend those boundaries without a D2 compiler fork. This release accepts no
width/lane/bus metadata or reserved extension syntax. Buses, wide ports, grouped
members, expansion views, type compatibility, connection obligations, behavioral
validation, conformance, native-test evidence and testcase generation remain
deferred. These internal seams are not a public plugin API.

The controlled acceptance cases cover multiple ports, nested imported reuse,
explicit exposures, editing stress/fan-out and opposite-direction wires, at both
zooms and repeated layouts. Larger production architectures require their own
acceptance evidence. Earlier stock-D2 layout failures remain historical results;
direct ELK is a separate implementation.

## Runnable repository examples

The checkout includes five [Codex, FFmpeg and Hx examples](https://github.com/CansWang/hierX/tree/main/tests/d2_bridge)
with a local README, pinned source slices and a shared source-navigation gallery:

```bash
cd tests/d2_bridge
./run.sh setup
./run.sh check all
./run.sh gallery --open
```

The local README covers individual cases, imports, code clicks, exports, browser
measurements and screenshot locations. Normal previews do not build the upstream
applications. These authored views and their navigation-only declaration catalog
do not establish extracted dataflow, complete architecture coverage or behavioral
validation. Generated galleries and images remain outside version control.
