# Repository example qualification — 2026-10-23

The five authored views pass the existing ordinary-port geometry gates with
upstream D2 v0.9.0 and direct elkjs 0.12.0. Every block and port opens its exact
declaration, signature, source filename/line and pinned source text in the
existing viewer. This qualifies these bounded presentations, not inferred
dataflow, complete repository architectures or contractual meaning.

| Case | Blocks | Ports | Arrows | Measured views | Actual code clicks |
|---|---:|---:|---:|---:|---:|
| Codex path resolution | 5 | 12 | 6 | 12 | 102 |
| Codex asynchronous search | 5 | 18 | 11 | 12 | 138 |
| FFmpeg transcode | 5 | 13 | 4 | 12 | 108 |
| FFmpeg audio/video reuse | 10 | 23 | 12 | 12 | 198 |
| Hx extraction/review | 7 | 16 | 9 | 12 | 138 |
| Total | 32 | 82 | 42 | 60 | 684 |

Each case uses three separate layouts at both 100% and 150% CSS zoom, measured
in fitted and actual-scale views. Measured
pin centers lie exactly on their assigned boundaries, and route endpoints have
zero distance from the corresponding pin boundaries. The existing tolerance is
unchanged at two SVG units. No label overlap, clipping, route through an
unrelated block, page error or incorrect code target was reported.

## What these examples establish

- Nested scalar exposures work with real API names and signatures.
- One imported codec-chain definition produces independent audio/video instance
  identities while preserving shared source targets.
- Query/result flows can run in opposite directions using separate scalar wires.
- A port can navigate to a different declaration than its owning block, including
  FFmpeg's paired send/receive APIs.
- A single gallery can serve Rust, C and Python source links without building
  upstream applications during normal preview.
- The pinned source/license payload is 635,882 bytes across 15 source files and
  seven license/notice files. The navigation catalog contains 35 real declarations,
  explicitly omitting call/type/global relationships and body hashes.

## Limits and practical findings

- Final fitted-view captures exposed a label touching its own boundary pin in
  Codex search: font hinting moved the glyph bounds slightly left when scaled
  down, although actual-scale checks passed. The native ELK adapter now requests
  eight SVG units of horizontal label/port spacing. Regression and acceptance
  checks cover fitted views too; geometry tolerances are unchanged.
- Fit-to-window labels become small in wide horizontal FFmpeg diagrams. Use
  zoom/pan or open a case outside its embedded gallery preview. Actual-scale
  geometry checks do not establish thumbnail text readability.
- The navigation catalog has no fabricated hierarchy edges. Most declarations
  have no path from its arbitrary entry node; direct links and source-viewer
  search still open them correctly. This is a declaration subset, not a merged
  multi-repository extraction result.
- Ports open owning declarations; parameter/return-token highlighting is deferred.
- Offline HTML includes diagram assets but no source bodies. Code links need an
  explicitly supplied matching live viewer URL.
- Original DOM SVG captures are debugging evidence; their stylesheet is in the
  enclosing HTML. Use HTML or PNG when viewing the presentation directly.
- Buses, bundles, width semantics, required connections, type compatibility,
  behavioral validation and testcase generation remain deferred.

## Verification records

`./run.sh check all --browser` passed 60 measured views (30 layout/zoom
combinations) and 684 clicks using Chromium 153.0.8010.12. The bridge SHA-256 was
`543b7023387c8a013bbe070a8a1577a76321d13bfb40d17bc5edf17a69280c2d`;
the ELK asset SHA-256 was
`1222e44f953ce7746af23801e723708f8e6f436b8b377a6a5fc7552f34a307b3`.

All **529 strict tests passed in 197.34 s, with no skips**, using
`HX_REQUIRE_TOOLS=1 HX_REQUIRE_VENDOR_TOOLS=xyce,xdm`. The **23 new regression
tests** also passed: the
repository cases, source/catalog damage, relocated paths with spaces, topology
and binding failures, source/annotation/history placement, foreground server
startup/browser URL/shutdown, offline exports, multilingual real clicks and
exported links into a matching live gallery. All **60 focused architecture/example
tests** passed after the port-spacing fix.

`./run.sh setup -- --no-bootstrap` also rebuilt and verified the helper using
the cached user-local Go 1.27.3 SDK. No source snapshot or historical acceptance
report was changed. The full-suite and documentation results are recorded in the
[SSOT](../../dev/ssot/single-source-of-truth.md).

Strict MkDocs passed. A separate missing-Chromium probe returned exit 2 with a
named error and a failing browser report, rather than treating unavailable
browser measurements as success. Coverage, wheel smoke and whole-repository
Codex extraction acceptance were not rerun for this example-only addition.

Reproducible commands and output locations are in [README.md](README.md).
Generated `.generated/reports/` holds detailed JSON; PNGs, DOM SVGs, layouts and
HTML galleries are ignored and can be regenerated. Original stock-D2 failures,
prior controlled Hx/ELK acceptance and the retired TOML archive remain separate
historical evidence.
