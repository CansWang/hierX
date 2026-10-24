# hx — Single Source of Truth (development strategy)

This file records the implemented baseline, intended direction, and decisions for
`hx`. The code is the truth for what exists; this file records what is intended
and the evidence for completed work. Update the **Status log** whenever a phase,
decision, or scope changes. Completed details are folded below, with their original
headings and dated results retained.

Folded sections use continuous HTML blocks for
[Typora compatibility](https://support.typora.io/HTML/). Edit their contents
as HTML, keeping each block free of blank lines; the current baseline and
Phase II roadmap remain ordinary Markdown.

## TLDR

- **Purpose.** Give developers and agents a compact structural view of software
  and hardware, with navigable evidence and concise changes after an edit.
- **Implemented.** Build-aware extraction → generated graph → browser review,
  annotations, structural diff, and CLI/Python/MCP queries. Human annotations
  survive regeneration through stable symbol IDs. The experimental Phase II.1
  TOML contract feature is [retired and archived](retired-toml-contracts.md).
- **Direction.** Accept D2 syntax for new architecture sketches, interpreted by
  Hx using upstream parsing rather than a D2 compiler fork. Start with blocks,
  individually named input/output ports, explicit connections, nested exposures,
  and code navigation. The ordinary-port profile now passes controlled direct-ELK
  presentation/navigation gates and is exposed through `hx arch inspect/serve/export`.
  The failed stock-D2 results remain historical evidence. TOML contract commands/APIs have been
  withdrawn; their source and acceptance evidence remain in the reference archive.
  [Buses, wide ports, and bundle expansion](#deferred-work-and-continuing-boundaries)
  move to future work. The [interface design](architecture-contract-interface.md)
  records the accepted syntax decision and staged scope. Further semantic checks
  and testcase generation remain deferred.

<a id="current-status-2026-10-18"></a>
<a id="current-status-2026-10-21"></a>
<a id="current-status-2026-10-22"></a>

## Current status (2026-10-23)

The committed baseline is **`2e54a84`**, which retains the verified Phase II.0
readiness foundation and retires the TOML prototype after a verified reference
snapshot; see the [retirement index](retired-toml-contracts.md). The uncommitted
Phase II.1b implements ordinary-port D2 authoring, interpretation, direct ELK
presentation and dedicated architecture commands after its controlled gate passed.
The package remains
**0.5.0**, graph
schema **hx/4**, and annotation schema **hx-ann/1**. The [README](../../README.md) and
[tutorials/API references](../../docs/index.md) describe the implemented interface.

Frontends produce a shared, bounded graph through `hx.api` and traversal. Graph
I/O, persistence, history, provenance, and diff support the CLI, Python, HTTP,
MCP, viewer, and export interfaces. Human annotations are stored separately.
This is the implemented extraction and review foundation for Phase II. Readiness
changes add evidence-limit metadata, shared Rust configuration discovery, strict
annotation JSON parsing, drive-entry validation, and graph availability handling.

| Completed capability | Implemented baseline |
| --- | --- |
| Extraction | C/C++ through libclang, SystemVerilog/Verilog through Verilator, Rust and Python through LSP, and native SPICE/ngspice/Xyce parsing; shared bounded traversal, stable IDs, types, edges, precision labels, and unresolved records. |
| Persistence and provenance | Tracked entries, shared saves, immutable retained snapshots, migration, and observed source/input/configuration fingerprints. |
| Annotations | Human-owned notes, tags, parameter overrides, source-hash review marks, shared managed storage, and guarded legacy import. |
| Viewer and change review | Source/type navigation, browser workflow tests, live reload, standalone export, structural diff, circuit net highlighting, definition/model navigation, and dedicated circuit changes. |
| Queries and automation | CLI and Python interfaces, HTTP service, MCP queries, tracking, polling watch, hooks, and saved-graph net/uses queries. |
| Architecture authoring and presentation | `hx arch inspect/serve/export`, upstream D2 v0.9.0 helper, ordinary boundary ports/wires/exposures, imported reuse, exact navigation links and offline HTML through direct elkjs 0.12.0; 24 controlled combinations pass. Five pinned Codex/FFmpeg/Hx sketches add 60 measured views and 684 genuine code clicks. Original stock-D2 profiles still fail their historical gate. |
| Hardening and distribution | Rust identity/token fixes, pinned Codex acceptance runner, independent syn audit, ngspice/Xyce/XDM checks, deterministic fake-simulator failures, migration tests, and isolated installed-wheel smoke in CI. |

The pre-implementation 2026-10-21 review ran:

```bash
PATH="$PWD/.venv/bin:$HOME/.cargo/bin:$PATH" HX_REQUIRE_TOOLS=1 HX_REQUIRE_VENDOR_TOOLS=xyce,xdm .venv/bin/python -m pytest -q -ra
```

Result: **417 passed in 195.67 s, no skips**. Strict MkDocs and all **five Node
viewer unit tests** also passed. All **22 explicit test references** in the
dialect matrix resolved, and all **10 SSOT folds** retained continuous HTML
without internal blank lines. MkDocs does not include `dev/ssot`; its build alone
does not validate this file's links or Typora behavior.

The **414-test, 91.8% line-coverage** result belongs to Phase 1.2; coverage was not
remeasured for this review. Production acceptance and wheel-smoke results retain
the dates and revisions of their original runs in the folded history. The findings
below retain their baseline reproductions. Implementation verification is recorded
separately so it does not replace historical results.

**Phase II.0 implementation verification:** **451 passed in 169.92 s, no skips**
with the strict required-tool and Xyce/XDM settings above; all **five Node tests**,
strict MkDocs, and the installed-wheel smoke passed. No new coverage or production
Codex acceptance measurement is claimed. The installed-wheel check includes Rust
extraction; the full production corpus is not rebuilt here.

**Historical Phase II.1 implementation verification (2026-10-21; feature now retired):** **508 passed in 178.59 s, no
skips**, with the same strict tool requirements. All **five Node tests**, strict
MkDocs, and installed-wheel smoke passed. The wheel includes all three new
schemas and executes contract validation and Rust projection outside the checkout.
The tutorial's **three Cargo tests** pass; baseline and bypass projections retain
source witnesses and coverage limits. Coverage and the production Codex corpus
were not rerun. Reports: `~/hx-review-artifacts/hierx-0.5/contracts-20261021-xet9w4vz/`.
The [retirement snapshot](retired-toml-contracts.md) preserves that implementation
and its reports; these results do not describe the remaining active feature set.

**Historical D2 experiment (2026-10-22):** the separate development harness tests ELK, Dagre, TALA, and
ELK with zero horizontal padding on flat, nested reused-child, and editing-stress
cases at 100%/150% zoom. All compile; none meets the visible boundary-pin gate.
All **72 focused tests** pass (13 private oracle/browser tests, 56 existing
contract tests, and three documentation-reference tests); strict MkDocs passes.
The oracle tests include real title/pin navigation against the existing
viewer and a cancelled-click negative case. The Rust example passes two Cargo
tests. See the [experiment and reproduction instructions](../d2_ports_experiment/README.md)
and `~/hx-review-artifacts/hierx-0.5/d2-ports-20261022-l9_xc0uu/run/` for the
matrix, original SVGs, geometry, screenshots, code-click outcomes, and findings.
This private experiment does not rerun or replace the recorded 508-test, wheel,
coverage, or production Codex acceptance results.

**TOML retirement verification (2026-10-23):** the remaining strict suite passed
**451 tests in 170.41 s, no skips**, with required tools and Xyce/XDM enabled.
The 57 TOML-feature tests were archived and removed, rather than skipped. All
**13 private D2 oracle/browser tests passed in 9.14 s**. Strict MkDocs passed.
A wheel built from a clean temporary source snapshot passed installed-wheel
smoke outside the checkout, including netlist, Xyce, and Rust extraction. It
contained ten required data files and four vendored viewer libraries, no retired
contract package/schemas, and rejected `hx contract` with the normal usage exit 2.
Shared graph-reader behavior and the D2 experiment are unchanged. No new coverage
or production Codex acceptance measurement is claimed. The
[retirement index](retired-toml-contracts.md) identifies the verified source/report
archive and separate current verification logs.

**D2 integration verification (2026-10-23):** **488 strict tests passed in
185.84 s, no skips**, with required tools and Xyce/XDM enabled. The final
architecture-focused checks passed **37 tests in 14.92 s**, including source
ranges and protocol validation under optimized Python. All **13 original private
D2 oracle/browser tests**, **five Node tests**, the Go bridge tests and strict
MkDocs passed. Controlled presentation acceptance passed **24 combinations and
288 genuine code clicks**. A clean installed wheel passed outside-checkout
netlist/Xyce/Rust/D2 smoke with 15 required data files, four vendored JavaScript
libraries and their attribution files; the retired TOML feature remains absent.
Reports and tool/source hashes are retained at
`~/hx-review-artifacts/hierx-0.5/d2-integration-20261024T001707Z/`.
No new coverage or production Codex acceptance measurement is claimed.

**D2 setup amendment (2026-10-23):** explicit bridge setup now installs verified
Go 1.27.3 under `~/.local/lib/go1.27.3` when no compatible Go 1.27+ is available.
The SDK remains installed, with a printed PATH command for interactive use;
system Go and shell profiles are unchanged. SDK reuse, `--go-dir`, opt-out through
`--no-bootstrap`, checksum rejection and atomic helper replacement are covered.
**51 focused checks passed with no skips**, including 18 installer tests, plus
Go tests and strict MkDocs. Actual missing-Go installation/build and cached-SDK
reuse passed; the rebuilt helper is byte-identical to the prior verified binary.
Reports: `~/hx-review-artifacts/hierx-0.5/d2-go-bootstrap-20261024T010316Z/`.
The full suite, wheel and presentation matrix were not rerun for this setup-only
amendment.

**Repository example verification (2026-10-23):** **529 strict tests passed in
197.34 s, no skips**, including 23 new source-snapshot/gallery checks. The five
Codex/FFmpeg/Hx examples separately passed **60 measured views and 684 genuine
source clicks**. Strict MkDocs, cached-SDK bridge setup, offline exports and a
named missing-Chromium failure also passed. The local
[guide and findings](../../tests/d2_bridge/README.md) distinguish authored intent,
declaration navigation and optional native extraction. Detailed current reports
are under `tests/d2_bridge/.generated/reports/`; generated visual assets remain
ignored. Native port-label spacing was corrected after the fitted-view probe
exposed a label touching its pin; both fitted and actual-size views are now gated.
No new coverage, wheel or whole-repository Codex measurement is claimed.

<details>
<summary>Implemented storage, annotations, and verification workflow</summary>
<ul>
<li><strong>State placement.</strong> Default CLI extraction walks upward from the real source file and selects the first directory containing <code>.github</code>, including nested repositories; <code>.hx</code> sits beside it. Without that marker it uses the invocation directory. Explicit <code>--root</code> takes precedence. Serve/export use invocation-local <code>.hx</code> first, otherwise the nearest <code>.github</code> owner's <code>.hx</code>, and error if the selected state has no graph. <code>graph.json</code> precedes sorted <code>graphs/*.json</code>; reserved <code>annotations.json</code> is excluded. Explicit graph paths bypass discovery.</li>
<li><strong>Persistence and provenance.</strong> CLI extraction, updates, MCP, viewer extraction and migration share <code>project.save_extraction</code>. Stable per-entry current files under <code>.hx/graphs/</code> coexist with the selected-entry mirror <code>.hx/graph.json</code>. Previous bytes become immutable history under <code>.hx/history/&lt;slug&gt;/</code>, with configurable retention (default 20). Time/revision/run-ID filenames distinguish extractions within the same commit; <code>meta.provenance</code> records Git/source state, observed inputs and option/result fingerprints. Explicit CLI <code>-o</code> selects standalone output. See <a href="../../docs/reference/configuration.md">storage rules</a>.</li>
<li><strong>Annotations.</strong> All managed graphs, including history, share their owning <code>.hx/annotations.json</code>; standalone graphs use adjacent notes. Serve/export <code>--annotations</code> overrides win, independently of source lookup. Viewer/MCP startup atomically copies one unambiguous legacy sidecar only when shared notes are absent, preserving its original bytes and file. Export can read that sidecar without importing. Competing or invalid legacy files require explicit selection or correction; no automatic merge occurs. Migration preflights notes before replacing graphs, then imports and maps IDs with the existing backup mechanism. See <a href="../../docs/reference/annotations.md#legacy-sidecars">legacy sidecars</a>.</li>
<li><strong>Viewer and CI.</strong> Browser workflow tests and hide/show UI are implemented; hidden state persists in annotations and exports. CI installs ngspice alongside the required language toolchains, Playwright and Chromium on Python 3.10/3.12. <code>HX_REQUIRE_TOOLS=1</code> fails required-tool skips; optional vendor checks remain opt-in through <code>HX_REQUIRE_VENDOR_TOOLS</code>. Documentation has a strict MkDocs build, interface coverage tests and executable tutorials.</li>
</ul>
</details>

## Evidence boundaries before Phase II

- **A saved graph is an entry view.** Workspace indexing by a frontend does not
  make its bounded output a whole-repository architecture. Multiple tracked
  entries remain separate graphs. The retired II.1 prototype reconciled compatible
  saved views and quarantined conflicting evidence within declared project/build
  domains. That behavior is archived reference material, not an active projection
  API or evidence of whole-repository coverage. Future D2 bindings need their own
  implementation and acceptance.
- **Extracted relations have a defined scope.** Calls, references, instances,
  reached types, and global accesses are useful evidence. They are not a complete
  module/package dependency model or runtime dataflow. A frontend's `module`
  node does not by itself identify an architectural component.
- **Precision and coverage constrain conclusions.** Depth/node limits,
  exclusions, unresolved dispatch, generated targets, and LSP precision must
  accompany a check. Absence of an edge in a bounded graph cannot establish
  a repository-wide prohibition. A language server can omit indirect calls
  entirely: the Rust fixture's `cb(&ch.desc, n as i32)` has neither an edge nor
  an unresolved record. An empty `unresolved[]` is therefore not a completeness
  certificate, even with unlimited traversal depth.
- **Provenance is observed evidence.** Current source and option fingerprints
  support comparison; they do not capture every compiler/server input or prove
  replayability. Rust toolchain/Cargo candidates are now observed before indexing
  and watched (R2); environment overrides and server-private inputs remain outside
  a complete build identity.
  There is no binding to a test build, binary, or execution yet.
- **Existing review signals have distinct meanings.** Annotation verification
  records human review against a source hash. `hx diff` compares two extracted
  implementations. Neither is an architecture-contract verdict or test result;
  `runtime` remains reserved and null.

## Review findings and follow-up register (2026-10-21)

P1 addresses evidence soundness and freshness, P2 runtime correctness, and P3
lower-priority validation/documentation work. Reproductions used temporary
workspaces; no saved project graphs or annotations were changed. Source links
identify the implementation locations; reproductions describe the reviewed
baseline before the fixes. R2–R5 are closed by **`1302535`** and the Phase II.0
acceptance results above. R1 has evidence-limit metadata but still needs
II.2 evaluator checks, now deferred with conformance work; R6 retains its
documented behavior. Graph and annotation
schema majors remain compatible. II.1's authored/projection formats and CLI/Python
interfaces are retired reference material; their removal does not close R1.

| ID / priority | Classification and status | Reproduction and impact | Remedy and acceptance criteria |
| --- | --- | --- | --- |
| **R1 / P1** | Confirmed frontend limitation; incorrect SSOT claim corrected here. **Evidence metadata implemented; conformance follow-up open.** | Extract `src/dma.rs:dma_start` from a temporary copy of `tests/fixtures/rust` with unlimited depth. The callback at line 60 has no edge or unresolved record and no frontend error. The earlier claim that all indirect calls become ghosts could justify false absence-based passes. See the [Rust guide](../../docs/guides/rust.md) and [LSP frontend](../../hx/frontends/lsp_fe.py). | State the coverage required by each obligation/frontend relation. II.2 must return `not established` when omitted calls could affect the obligation, including cases with an empty unresolved list; witnessed forbidden dependencies can still establish violations. Implemented: optional sorted `meta.evidence_limits` emits `entry-view-only` for every frontend and `lsp-call-omissions` for LSP; missing/empty metadata is unknown coverage. The deterministic omitted-call test in [test_lsp_fe.py](../../tests/test_lsp_fe.py) checks empty edges/unresolved/errors, schema validation, save/load/export, legacy absence, and unchanged structural diff. |
| **R2 / P1** | Confirmed configuration-discovery gap. **Closed in `1302535`; II.0 acceptance passed.** | Compare `project.source_signature(root)` before and after creating `rust-toolchain.toml` and `.cargo/config.toml`: the signature is unchanged. Default watching misses these build inputs, and current recognized-config provenance does not cover them. See [watching](../../hx/project.py) and [provenance](../../hx/provenance.py). | Discover relevant Rust toolchain and Cargo configuration inputs explicitly, including missing candidates. Test creation, edit, and deletion, watch-triggered refresh, and input fingerprint changes. II.3 must reject stale evidence when relevant configuration changes. Implemented in [config_inputs.py](../../hx/config_inputs.py), the LSP frontend, and project watching. [test_config_inputs.py](../../tests/test_config_inputs.py) covers root/ancestor/Cargo-home and legacy/missing candidates, startup races, restricted watch paths before extraction, saved provenance, and live Rust extraction. |
| **R3 / P2** | Confirmed annotation HTTP error-handling bug. **Closed in `1302535`; II.0 acceptance passed.** | Send malformed JSON, such as `{`, to annotation PATCH: HTTP 500, with existing bytes unchanged. Both write handlers parse JSON without translating decode errors. See [annotation routes](../../hx/serve/app.py). | Return HTTP 400 with a useful JSON error for malformed PUT/PATCH bodies. Verify that stored annotations, revision, and emitted annotation events are unchanged after rejection. Implemented: both routes reject malformed/empty/invalid-encoding JSON with 400. [test_serve.py](../../tests/test_serve.py) checks bytes, revision, and events remain unchanged and preserves the documented non-object PUT behavior. |
| **R4 / P2** | Confirmed graph lifecycle bug. **Closed in `1302535`; II.0 acceptance passed.** | Initialize server state with a tracked graph, delete that file, then call `State.poll_files()`: no change event is returned although the graph disappears from discovery. A connected viewer can retain stale content. See [server watching](../../hx/serve/app.py). | Detect deletion and refresh graph availability. Test deleting primary and tracked graphs, a clear unavailable state for the selected graph, and recovery after recreation; unchanged files must not emit repeated events. Implemented: one creation/deletion event per observed transition; selected graph identity persists while content/actions clear, queued annotations survive, and recreation recovers. [Server tests](../../tests/test_serve.py) and [browser tests](../../tests/test_e2e_viewer.py) cover primary/tracked files, initial absence, picker refresh, delayed graph/source/history/diff responses, and annotation revision resets after a server restart. |
| **R5 / P3** | Confirmed entry-validation bug. **Closed in `1302535`; II.0 acceptance passed.** | `split_entry(r'C:\src\main.rs')` returns a truncated filename and the whole input as a symbol instead of rejecting the missing separator. See [entry parsing](../../hx/api.py). | Reject a drive-qualified path without `:symbol` before filesystem access. Preserve valid drive paths with symbols and qualified names such as `src/main.cpp:hw::run`. Implemented and covered by drive-path rejection and qualified-symbol preservation cases in [test_paths.py](../../tests/test_paths.py). |
| **R6 / P2** | Documented data-loss risk; **compatibility proposal**, not an undocumented bug. | After saving a note, PUT `[]` to `/api/annotations`: HTTP 200 and an empty annotation document. The [HTTP reference](../../docs/reference/http.md#put-apiannotations) explicitly documents this normalization. | Proposed hardening: accept only object PUT bodies and reject other JSON values with HTTP 400 before any write/revision/event. Preserve intentional clearing with `{}`. This changes documented behavior and needs coordinated API documentation, release notes, and regression tests; it is outside the readiness gate. |
| **R7 / P3** | Documentation drift. **Corrected in this amendment.** | Contributor instructions called the ngspice tutorial vendor-opt-in, but `test_netlist_oracle_tutorial` calls `require_tool("ngspice")` and CI installs it. | Align [contributor instructions](../../docs/contributing.md) with the [required/vendor policy](../../tests/conftest.py): `HX_REQUIRE_TOOLS=1` requires ngspice; Xyce/XDM vendor requirements remain opt-in. |

Close an implementation finding only with a fix revision and its acceptance
results; retain its reproduction and original classification. The implementation
rows above identify committed fixes and their acceptance evidence. R1's metadata does not establish evaluator coverage, and
R6 remains a proposal until the documented behavior is deliberately changed.

<a id="phase-ii-architecture-contracts-planned"></a>
<a id="phase-ii-architecture-contracts-in-progress"></a>

## Phase II — Architecture authoring and composition (revised direction)

The immediate goal is readable architectural authoring and presentation with
blocks, named input/output ports on block boundaries, labelled connections,
nested blocks exposing child ports, and clickable code links. Keep this small Hx
concept separate from contractual meaning. **D2 syntax is selected for new
architecture sketches.** Reuse upstream D2 parsing with an Hx interpretation
layer rather than maintaining a D2 compiler fork. Begin with ordinary,
individually named ports and connections; defer buses, wide ports/signals, and
bundle expansion. Direct ELK layout with native ports and hierarchy now passes
the controlled ordinary-port presentation/navigation gate, with dedicated
preview/export commands.
This deliberately relaxes the earlier requirement that stock D2 produce all
geometry.

The separate [interface design note](architecture-contract-interface.md) explains
the retired service-interface model, the implemented D2 profile and its acceptance
criteria, future bus/width support, and the retained earlier TOML input/output
proposal. Arrows between dataflow ports describe data or signal flow. This
implementation retains the staged scope; automatic migration remains unimplemented.

The experimental TOML contract model, loader, bindings, projection, and commands
have been withdrawn from the active package. The
[reference snapshot](retired-toml-contracts.md) preserves their source, tests,
schemas, documentation, and original acceptance reports. Projection's useful
evidence-reconciliation ideas remain coupled to the old model in that snapshot;
no generic backend has been extracted. D2 navigation bindings are implemented;
component ownership/projection and migration are not. Conformance evaluation, native-test evidence binding, and generated
testcases remain deferred.
This **Phase II** is a new development stage; the historical **Phase 2** below
is the completed viewer/server milestone.

```text
D2 authoring → Hx blocks/individual ports/connections → direct ELK → Hx presentation
                                                           ↓
                              boundary-pin/connection/code-navigation acceptance
Source + build configuration → existing hx graphs and source viewer
```

The first experiment uses a separate safe Rust fixture and the existing source
viewer. Native tests keep that example executable; they are not architectural
test evidence. Its failed stock-D2 results remain unchanged below. The separate
Hx/D2 experiment passed ordinary named ports, explicit wires, nested individual-port
exposures, and code links. Bus/bundle and width-specific handling stay in future
work. Extend to production examples only after a candidate passes the controlled
presentation and navigation gates. Continue existing
frontend and circuit regression coverage. The earlier conformance/test-evidence
design is retained below for a future decision, with its original acceptance
conditions.

### II.0 — Readiness stabilization

The **readiness foundation is committed in `1302535`**: R2–R5 code,
regressions, and R1 evidence-limit metadata. Current graph/annotation schemas and
symbol IDs remain compatible. Rust configuration candidates are shared between
extraction and watch, captured before server startup, and retained when missing.
The viewer clears a deleted selected graph without changing its identity or
losing pending notes, then recovers on recreation.

**Implementation acceptance:** focused tests exercise R1 metadata and R2–R5
failures, followed by the strict suite, Node tests, strict docs, and installed-wheel
smoke. Final results are recorded in Current status and the dated log. Coverage
and full production Codex acceptance retain their earlier measurements.

**Conformance acceptance remains gated:** II.2 must consume evidence limitations
and return `not established` when an obligation lacks adequate coverage, including
omitted calls with empty unresolved lists. R1 stays open until these evaluator
checks exist; emitting metadata alone cannot establish a verdict. R6 remains a
separate compatibility proposal, and R7's contributor-policy correction is done.
The retired II.1 reference supplied authored intent, composition, bindings, and a
controlled Rust fixture. Its code and evidence are archived. II.2 and native-test
evidence ingestion in II.3 remain deferred while the D2 authoring/presentation
implementation is developed.

<a id="ii1-intent-composition-and-component-bindings"></a>

### II.1 — Intent, composition, and component bindings (retired reference)

**Retired from the active package on 2026-10-23.** The following describes the
historical prototype, not a current API. Its
[format reference and Rust tutorial](retired-toml-contracts.md#archived-source)
are in the verified reference archive. No conformance evaluator or test-evidence
ingestion was included.

- Authored `hx-contract/1` TOML supplies named components, provided/required
  logical interfaces, local reusable child files, explicit connections/exposures/
  delegation, declared dependencies and qualified test obligations. Missing
  includes, cycles, invalid wiring/types, duplicate names and unconnected child
  requirements produce diagnostics. Parent and child obligations are retained
  together; a future II.2 evaluator must not infer parent success from children.
- Separate `hx-bindings/1` TOML names projects, configurations and saved graphs.
  Exact IDs and project-relative file patterns bind qualified component instances;
  provided interfaces bind directly owned symbols or explicitly expose child
  ports. One direct owner per `(project, configuration, node ID)`; ancestors
  aggregate descendants. Empty selectors, absent symbols, ownership overlaps,
  duplicate declarations and foreign interface ownership are errors. Unassigned
  observations remain visible.
- Reconciliation compares shared known source/build observations and symbol
  definitions. Entry/depth and observed-file subsets may differ: whole option and
  input-set hashes are retained, not required to match. Conflicts, unstable inputs,
  unreadable graphs and unsettled migrated identities quarantine a domain while
  retaining available manifests. Unknown coverage/provenance remains unknown.
- `hx.contracts` and `hx contract validate/project` expose deterministic reports,
  text or JSON. `hx-projection/1` preserves authored intent, memberships, interfaces,
  source witnesses, graph provenance, unresolved records, errors and evidence
  limits. All inputs are read-only; optional output must be a new derived file.
  Existing `hx/4`, annotations, MCP and viewer flows are unchanged.
- The safe Rust fixture contains application → service → storage, two nested
  instances of one cache contract, three ordinary Cargo tests, and a bypass entry
  with a witnessed application → storage call. The bypass is projected, not yet
  assigned a conformance verdict; Cargo outcomes are not ingested as evidence.

**Historical acceptance:** the archived [unit tests](retired-toml-contracts.md#archived-source) cover composition,
selectors, scoped identity, conflicting inputs, read-only output, schemas, and
ordering. Archived [live tests](retired-toml-contracts.md#archived-source) execute the published
Cargo/extraction/projection tutorial and reconcile overlapping Rust entry views.
Equivalent declaration/observation order preserves the semantic projection;
exact-byte input hashes change when authored or saved input bytes change.
The archived installed-wheel smoke exercised those commands outside the checkout.
Historical results remain in Current status and the dated log; current packaging
instead verifies that the retired feature is absent.

### II.1a — D2 boundary-port feasibility experiment (completed; gate failed)

The [private harness](../d2_ports_experiment/README.md) keeps D2 v0.9.0 outside the
production dependency/CLI surface. It uses unmodified ELK, Dagre, and TALA engines,
plus native ELK zero horizontal padding. Hx measures SVG output and supplies code
links; it never moves a pin or repairs a route. The small Python fixture records
are an independent test oracle, not another architecture input format or parser.

**Required demonstration:** multiple named inputs on left borders and outputs on
right borders; wires reaching the correct visible pins with readable labels;
nested imported/reused children with explicit exposure wires; actual clicks on
block titles and port glyphs opening the expected code and signature. Pin centres
and wire tips have a two-SVG-unit tolerance, independent of browser zoom. Table-row
anchors are a comparison only and cannot satisfy the visible-pin requirement.

**Observed result:** none of the four profiles passes all three cases at either
100% or 150% zoom. Circle children remain inside containers; even zero-padding
ELK leaves centres at least five units from their assigned borders. D2's native
link icons obscure the ten-unit pin centres. Block-title links generally work;
some nested/stress layouts also have endpoint and label problems. Original SVGs
and exact per-case metrics are retained, without post-layout geometry changes.
Profiles that fail the initial gate are not repeated; a future passing profile
must also pass two further compilations with stable identities/topology.

**Decision:** keep the TOML implementation and do not start a D2 migration from
this result. Reconsider D2's role or evaluate another presentation approach in a
separately scoped experiment. A port-aware renderer would change the selected
pure-D2 constraint and is a future option, not an implemented workaround. These
fixtures do not establish impossibility for every D2 encoding. Before any
integration, a candidate must pass the same boundary-pin, exposure, label, click,
and edit-stability gates. Parameter/return ports currently link to the owning
function; exact token highlighting and semantic/dataflow claims remain outside
the experiment.

### II.1b — Hx/D2 interpretation and direct ELK layout (implemented; controlled gate passed)

<a id="ii1b-hxd2-interpretation-and-direct-elk-layout-next-experiment-unverified"></a>

D2 syntax is accepted and implemented for ordinary-port architecture authoring.
A thin optional Go bridge calls unmodified D2 v0.9.0 compilation; Hx interprets
blocks, individually named ports, explicit connections/exposures and navigation
bindings, then presents native-port elkjs 0.12.0 layout. No compiler fork is used.
[ELK Layered](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html)
documents native ports, port constraints, and compound/cross-hierarchy layout;
that motivated the candidate; its controlled Hx gate now supplies measured evidence.

**Delivered:** `hx arch inspect` returns a summary or derived `hx-arch/1` JSON;
`hx arch serve` opens a dedicated preview and optional existing source viewer;
`hx arch export` embeds diagram/runtime assets in standalone HTML. Saved code
graphs are explicit inputs. Export code links need an explicit viewer URL and do
not embed source. Explicit setup uses compatible Go 1.27+ or installs a verified,
persistent user-local Go 1.27.3 SDK before building the helper; `--no-bootstrap`
disables SDK installation. Runtime commands perform no downloads. Architecture
data and layout remain separate from `hx/4`/annotations.

**Controlled result:** flat, nested imported/reused-child, stress/fan-out and
opposite-flow scalar cases passed all 24 combinations (three layouts and two
zooms per case), including independent geometry checks and real source/signature
clicks. Reports and original SVGs are in
`~/hx-review-artifacts/hierx-0.5/d2-integration-20261024T001707Z/`.
This is controlled presentation acceptance, not a production Codex measurement.

**Repository examples:** [five runnable sketches](../../tests/d2_bridge/README.md)
cover Codex path resolution and asynchronous search, FFmpeg transcoding and
reused audio/video paths, and Hx extraction/persistence/review. Small pinned
source slices retain licenses and hashes. A locally rebased declaration catalog
supports every block/port link through one gallery/source server without building
the upstream applications. It contains no invented call edges and explicitly
omits relationships; declaration precision does not qualify the authored wires.
The examples passed **60 measured views and 684 actual source clicks**, with
three layouts and 100%/150% zoom per case. Their local README documents setup,
editing, exports, optional native extraction and checks. Generated visual assets
stay ignored; [compact findings](../../tests/d2_bridge/FINDINGS.md) are retained
alongside the examples. Wide fitted
views require zoom/pan for individual labels. These bounded views do not establish
whole-repository architecture coverage, scale limits, or conformance.

**Extension seams:** keep the D2 adapter, interpreter, authored document,
navigation resolver, ELK graph adapter and SVG presenter independent. Future bus/
bundle normalization can precede layout and preserve member identities through
expanded views. These are internal boundaries, not accepted width/bus syntax,
placeholder fields or a public plugin framework. Unknown Hx roles fail explicitly.

**Immediate acceptance:** demonstrate multiple named input/output boundary pins,
explicit connections between those pins, nested exposure of individual child
ports, distinct reused-instance identities, and working code links from blocks
and ports. Opposite-flow scalar connections remain separate wires. Retain the
two-SVG-unit geometry tolerance, 100%/150% zoom checks, edit-stress cases, and two
further stability runs after an initial pass. Keep missing measurements or
unresolved code targets explicit.
Full criteria are in the [interface design note](architecture-contract-interface.md#next-experiment-hxd2-interpretation-and-direct-elk-layout).

This relaxes the stock-D2-only geometry constraint for the new experiment.
Preserve II.1a and its original artifacts/results; direct ELK gets separate
evidence. Preserve the retired TOML implementation in its external archive and
retain the earlier TOML dataflow proposal as a historical reference. D2 syntax is
implemented, but navigation links do not supply a projection backend from this
retirement. Move bus/bundle definitions, wide ports/signals, bundle
expansion, mixed-direction bundles, and child-bundle exposures to the
[future plan](architecture-contract-interface.md#future-plan-buses-and-wide-ports);
they are not initial acceptance gates. Type compatibility,
required-connection obligations, behavioral validation, and
testcase generation remain deferred. The ordinary-port renderer qualifies on the
controlled cases; broader production acceptance and authored-contract migration
remain separate work.

<a id="ii2-structural-conformance-and-explanations"></a>

### II.2 — Structural conformance and explanations (deferred)

Future D2 ownership/implementation bindings and component projection are not implemented.
The retired prototype is a reference for later evidence handling, not an active
backend on which these checks can run.

- Evaluate supported interface and dependency obligations against the component
  projection. Begin with required relationships, permitted/prohibited dependencies,
  and parent/child wiring; state which frontend relations each check can use and
  what coverage each verdict requires. Include known frontend omissions alongside
  reported unresolved targets and extraction errors.
- Give each obligation one result: **satisfied**, **violated**, or **not
  established**. A witnessed forbidden dependency can establish a violation even
  in a partial graph. A positive result requires adequate evidence for that
  obligation; missing bindings, unresolved targets, or insufficient coverage
  cannot silently become a pass.
- Attach the contract obligation, component bindings, source witnesses, input
  identity, and relevant limitations to findings. Keep structural conformance
  separate from native test outcomes so a green test cannot erase a structural
  violation or an evidence gap.

**Acceptance gate:** allowed dependencies, deliberate violations, missing required
interfaces, failed composition, truncated views, incompatible configurations,
and unresolved or omitted indirect calls produce explainable, distinguishable
results. An empty unresolved list must not turn a coverage gap into a satisfied
absence-based obligation. Repeated evaluation is deterministic and read-only
with respect to authored intent and saved graphs.

<a id="ii3-compiled-native-test-evidence"></a>

### II.3 — Compiled native-test evidence (deferred)

- Build and run the project's native tests, beginning with Cargo tests in the
  controlled Rust fixture. Link named test obligations to selected test results;
  merely having tests in a package does not discharge every obligation. A zero
  exit status with zero selected tests or only ignored tests cannot satisfy a
  test obligation; record the selected and actually executed tests.
- Associate evidence with the contract revision, source state, extraction/build
  configuration, target/features, toolchain, build artifact identity, and test
  invocation. Extend the evidence model beyond current observed-input provenance
  wherever those inputs are needed to establish that the records match, including
  relevant Rust toolchain/Cargo configuration and build-affecting environment.
- Retain build and execution outcomes and small diagnostic reports. Distinguish
  compilation failure, test failure, timeout, unavailable tools, missing evidence,
  and stale evidence. Changed contracts, sources, or relevant configurations
  require fresh matching evidence before a test obligation can be satisfied.
- Keep compilation, successful execution, and demonstrated architectural paths
  distinct. Passing a linked test establishes its recorded test outcome; proving
  a particular call path or coverage needs later instrumentation. Generated
  executable contract tests are deferred beyond this initial native-test scope.

**Acceptance gate:** actual Rust builds and test runs cover passing and failing
tests, build failure, unavailable tools, timeouts, zero selected/only ignored
tests, and stale source/contract/configuration evidence. Matching results link to
their obligations without altering structural verdicts or human review marks.

<a id="ii4-review-integration-and-production-acceptance"></a>

### II.4 — Review integration and production acceptance (deferred)

Resume this conformance/test-evidence integration only after an explicit scope
decision. A future presentation integration has its own preceding gate above.

- Expose the same conformance findings and native-test evidence through CLI,
  viewer, standalone export, and MCP. Support component navigation, source
  witnesses, limitations, and linked test outcomes; reuse existing consumers
  while keeping structural diffs distinct from intent-versus-implementation checks.
- Validate the complete flow on the controlled Rust fixture, including a composed
  architecture with passing children but a violated parent connection. Then add
  representative pinned Codex cases with explicit source/toolchain/build settings
  and selected native test commands. Codex acceptance must exercise the new
  contract flow, beyond the existing extraction/syn parser audit.
- Retain compact reports, findings, input identities, and diagnostic evidence.
  Keep production runs explicit and build caches rebuildable with a documented
  cleanup lifecycle. Historical reports remain evidence of their recorded runs.

**Acceptance gate:** interface and browser tests agree on findings and evidence;
exports retain the explanations. A pinned Codex run records structural results,
selected native-test results, and explicit unavailable or incomplete evidence.
The existing strict suite, strict docs build, and installed-wheel smoke stay green.

## Deferred work and continuing boundaries

- **Buses and wide ports:** defer bus/bundle definitions, width/vector/lane
  handling, width-labelled wide signals, bundle collapse/expansion,
  mixed-direction bundle roles, and parent exposure of complete child bundles.
  Start with individually named ports and explicit wires. The
  [future interface plan](architecture-contract-interface.md#future-plan-buses-and-wide-ports)
  retains the wide-signal, expandable-bundle, mixed-direction-handshake-bundle,
  and nested-bundle demonstrations with code links for a later phase.
- **Contractual semantics:** further type compatibility and required-connection
  checks, behavioral obligations, conformance evaluation, native-test evidence
  ingestion, and testcase generation are deferred. The retired TOML prototype is
  reference material only; the D2 experiment introduces no new verdicts.
- **HSPICE/Spectre:** defer syntax support until the relevant tools are available.
  Preserve the native SPICE/ngspice/Xyce scope and independent oracle boundaries
  in the [dialect matrix](netlist-dialect-matrix.md). Numeric model-bin selection,
  unsupported device families, and `.alter` remain documented dialect limits.
- **Dynamic evidence:** runtime tracing, coverage/path instrumentation, and
  generated executable contract tests remain later work. Running native project
  tests in Phase II does not populate the reserved graph `runtime` slot or imply
  that dynamic architectural behavior was observed.
- **Extraction infrastructure:** inotify watching, C++ template-instantiation
  expansion, LSP disk caching, and per-always-block SV signal reads/writes remain
  outside implemented scope. Architecture composition must respect current
  frontend precision and bounded traversal rather than assume these are solved.

## Principles
1. **Make observed gaps explicit.** Targets reported by a frontend but not expanded retain unresolved reasons (depth, missing definition, exclusion, truncation, or unsupported target). A frontend can omit relationships entirely, especially indirect LSP calls; describe those capability limits separately. Absence of unresolved records does not prove complete extraction.
2. **IDs are a contract.** `<lang>:<relpath>::<qualname>` forms are stable across regeneration of the same build configuration; C++ IDs include parameter types to distinguish overloads, with hashes for residual collisions. A C/C++ type that differs between translation units carries `@<8hex>` (hx/3). Annotations key on IDs, and an identity rule change bumps the schema major with a migration.
3. **Exactness is labelled.** Every node carries `precision` (`exact` | `lsp` | `syntax`); every param carries `dir_source` (`explicit` | `heuristic` | `user`). The viewer never pretends.
4. **Regeneration is cheap.** Per-TU cache keyed by source+header mtimes; a re-run after an agent edit re-parses only what changed.
5. **Frontends emit IR, nothing else.** `hx/traverse.py` never looks inside a frontend key.
6. **Human-owned data lives apart from generated data.** `graph.json` vs `annotations.json`.

## Risks / mitigations
- **Controlled D2/ELK acceptance is not production-scale acceptance** → preserve
  original stock-D2 failures and separate passing Hx/ELK evidence. Pinned Codex,
  FFmpeg and Hx sketches add bounded presentation coverage, not whole-program
  extraction or architecture validation. Add larger cases before broader claims;
  keep boundary-pin, label, endpoint, code-click and edit-stability gates for each
  extension. Wide fit views need zoom/pan. Buses/widths stay deferred.
- **Cross-compiler flags break libclang** → `--target` + sysroot auto-detect, `--extra-arg` escape hatch, per-TU error list in `meta.tu_errors`.
- **Macro-heavy register code** → macro spans + spelled args; `kind: macro` edges.
- **Large repos** → per-TU cache + multiprocessing + depth/max-nodes limits.
- **LSP frontends less exact** → `precision` surfaced in the viewer.
- **Dynamic dispatch / function pointers omitted** → unresolved records cover reported targets, while frontend omissions need explicit coverage limits (R1); II.2 must not infer completeness from an empty list.
- **Build-input identity incomplete** → observed fingerprints remain useful but cannot certify a matching test build; Rust configuration discovery is implemented (R2); bind relevant source/configuration/toolchain/artifact identity in II.3.
- **Toolchain drift** → ordinary CI installs floating Rust `stable`, while production acceptance pins source and tools. Preserve each run's actual identities and keep reproducible acceptance distinct from compatibility checks against newer tools.
- **Invalid writes and stale live views** → reject malformed annotation requests without side effects (R3) and handle graph deletion/recreation (R4). Treat stricter PUT normalization as an explicit compatibility change (R6).

## Conventions
- Python 3.10+, dataclasses over pydantic for the IR, no network at runtime, vendored browser libs.
- Tests: `python -m pytest -q` from the repo root (venv at `.venv`). Fixture projects are copied to a temp dir per test.
- Do not commit on the user's behalf; the user decides when to commit.
- Keep this file's Status log current.
- Validate SSOT links, anchors, and continuous HTML folds separately from MkDocs; use Typora to verify edited folded bodies. A prose-only amendment needs documentation checks, not a new full-suite/coverage/production-acceptance claim.

## Completed work and retained design history

The expandable sections preserve implementation decisions, superseded schemas
and identities, original milestone numbers, and dated experiments. Their open
items and test counts describe their original points in time; the current
baseline and deferred-work section above determine present status. The original
runtime reservation is retained here as history, not a Phase II prerequisite.

<details>
<summary>0.5.0 implementation and test map</summary>
<ul>
<li><strong>Where the 0.5.0 code lives.</strong> Root and graph discovery <code>hx/paths.py</code> (<code>tests/test_paths.py</code>); persistence <code>project.save_extraction</code> and history (<code>tests/test_persistence.py</code>); shared annotations and legacy sidecars (<code>tests/test_annotation_storage.py</code>); <code>hx/provenance.py</code> (<code>tests/test_provenance.py</code>); Rust token helpers <code>hx/rustsyntax.py</code> and the hx/4 Rust identity rules (<code>tests/test_rust_hardening.py</code>, fixture <code>tests/fixtures/rust_hardening/</code>, development-only syn oracle <code>dev/rust-oracle/</code>); Xyce profile and inventory <code>hx/netlist/profiles.py</code> + <code>hx/netlist/xyce_devices.json</code>, Xyce/XDM checks <code>hx/netlist/xyce.py</code> (<code>tests/test_xyce.py</code>, fixtures <code>tests/fixtures/xyce/</code>, fake-simulator failure paths <code>tests/test_netlist_oracle_fakes.py</code>); saved-graph queries <code>hx/netlist/query.py</code> with the viewer's <code>hx/viewer/circuit.js</code> and <code>tests/js/circuit.test.mjs</code> (<code>tests/test_netlist_query.py</code>, fixture <code>tests/fixtures/viewer/circuit-query.json</code>); schema <code>hx/schema/hx-4.schema.json</code>; tutorials and examples <code>docs/</code>, <code>examples/prepare.py</code>, <code>examples/inspect_graph.py</code> (<code>tests/test_tutorials.py</code>, <code>tests/test_docs.py</code>); acceptance runner <code>dev/scripts/hardening_coverage.py</code>, artifacts <code>~/hx-review-artifacts/hierx-0.5/</code> (<code>rust-acceptance/</code> is the passing run; <code>rust-acceptance-v2..v4</code> are superseded failures kept for the record); installed-wheel smoke <code>dev/scripts/wheel_smoke.sh</code>.</li>
</ul>
</details>

<details>
<summary>Glossary and original project context</summary>
<p><strong>Tool shape and design decisions retained from the pre-Phase II SSOT:</strong></p>
<ul>
<li><strong>Problem</strong>: AI agents flood the developer with text. The developer wants a compact, always-current, <em>structural</em> view of the code the agents touch, for software and hardware codebases alike.</li>
<li><strong>Tool shape</strong>: <code>hx extract &lt;file&gt;:&lt;symbol&gt;</code> → <code>graph.json</code> (functions, params with in/out, types, structs, call edges, per depth) → <code>hx serve</code> (browser UI, interactive, annotatable, live-reload) → <code>hx diff</code> (what changed between two extractions, in ~20 lines).</li>
<li><strong>Two files, not one</strong>: machine-generated <code>graph.json</code> is regenerated freely; human-owned <code>annotations.json</code> (notes, tags, in/out overrides, "verified" marks) survives regeneration via stable symbol IDs.</li>
<li><strong>One IR, five frontends</strong>: language-neutral intermediate representation; frontends for C/C++ (libclang), SystemVerilog (verilator XML), Rust + Python (generic LSP client) and SPICE-family circuit netlists (native parser, simulators only as optional oracles). C/C++ first.</li>
<li><strong>Decisions made</strong>: metadata format = JSON (schema-versioned; SQLite only if repo-scale indexing is later needed). Tool = Python package. Viewer = browser app bundled into one HTML with vendored libraries (Cytoscape.js + dagre), served by FastAPI. Static structure only; runtime capture reserved for a later phase.</li>
</ul>
<h2 id="glossary">Glossary</h2>
<ul>
<li><strong>IR</strong> — intermediate representation, the language-neutral data model in <code>hx/model.py</code>.</li>
<li><strong>Call graph</strong> — who-calls-whom.</li>
<li><strong>libclang</strong> — Clang's C API for parsing C/C++ with full type info. Used through the pip <code>libclang</code> wheel plus the system clang resource dir.</li>
<li><strong>compile_commands.json</strong> — per-file compiler flags, emitted by CMake (<code>CMAKE_EXPORT_COMPILE_COMMANDS=ON</code>) or Bear.</li>
<li><strong>USR</strong> — Unified Symbol Resolution, libclang's cross-file identity string for a symbol. Internal only; mapped to stable IDs.</li>
<li><strong>TU</strong> — translation unit, one <code>.c</code>/<code>.cpp</code> file plus its includes.</li>
<li><strong>LSP</strong> — Language Server Protocol, the editor-agnostic "go to definition / call hierarchy" API.</li>
<li><strong>MCP</strong> — Model Context Protocol, how agents call external tools.</li>
<li><strong>SSE</strong> — Server-Sent Events, one-way push from server to browser.</li>
<li><strong>BFS</strong> — breadth-first search.</li>
</ul>
<h2 id="context">Context</h2>
<ul>
<li>Repo <code>~/hx</code> started empty on 2026-10-09; tool working name <code>hx</code> matches the repo.</li>
<li>Dev machine: Python 3.12, Node 20, clang 18 (resource dir <code>/usr/lib/llvm-18/lib/clang/18</code>), verilator 5.02 (<code>--xml-only</code> dumps elaborated module hierarchy with ports/types), graphviz, sqlite3, Google Chrome (headless screenshots for viewer checks). Not installed at the start: clangd, tree-sitter, rust-analyzer, cargo, pyright (rust-analyzer, cargo and pyright were installed for Phase 3, see the status log).</li>
<li>User choices: languages C/C++, SystemVerilog/Verilog, Python, Rust; build-aware exact extraction; local server + static export; static only for now.</li>
<li>Motive to keep central: after an agent session the human should read a <strong>short structural diff + an updated graph</strong>, not agent output. Agents should be able to <strong>query</strong> the graph instead of re-reading files.</li>
</ul>
</details>

<details>
<summary>Original phase index and runtime reservation</summary>
<h2 id="phases-high-level">Phases (high level)</h2>
<ol type="1">
<li><strong>Core + C/C++</strong> — IR, stable IDs, BFS traversal, CLI, libclang frontend, JSON output, fixture tests. <strong>Done 2026-10-09.</strong></li>
<li><strong>Viewer + Serve</strong> — single-file browser UI (tree / graph / detail panes), FastAPI server persisting annotations, SSE live-reload, static HTML export. <strong>Done 2026-10-09.</strong></li>
<li><strong>More frontends</strong> — SystemVerilog via verilator XML; generic LSP frontend driving rust-analyzer and pyright; shared conformance fixtures. <strong>Done 2026-10-09.</strong></li>
<li><strong>Diff + agent integration</strong> — <code>hx diff</code> (Markdown + JSON), post-edit hook that re-extracts configured entries, MCP server so agents query the graph. <strong>Done 2026-10-09.</strong></li>
<li><strong>Hardening (4.5)</strong> — the eight defects from the external review, tautological tests, reproducible toolchain coverage, documented boundaries. <strong>Done 2026-10-10.</strong></li>
<li><strong>Real-project hardening (4.6)</strong> — the eleven findings from the CVA6 review (wide constants, SV cache identity, specialized type identity, generated instances, viewer layout failure, anonymous SV ids, source ranges, warnings, entry validation, generate-array spelling, version) plus schema <code>hx/2</code> with migration. <strong>Done 2026-10-10.</strong></li>
<li><strong>Review fixes (4.7)</strong> — the nine defects of the FFmpeg C review (C-C1…C4) and the apragma Python review (PY-H1…H5) plus the two found while verifying them (struct-tag USR collision, Pyright overload fan-out): shared lexer, file-scoped C identity with cross-TU type reconciliation and SCC fingerprints, nested LSP qualnames, module nodes, caller admission before fetch, schema <code>hx/3</code> with the 1→2→3 upgrade chain and location-based migration, review bundles replayable against a fixed checkout. <strong>Done 2026-10-12.</strong></li>
<li><strong>Runtime (reserved, not now)</strong> — IR already carries an empty <code>runtime</code> slot; instrumentation strategies noted only.</li>
<li><strong>Circuit netlists</strong> — N1 SPICE + ngspice end to end <strong>done 2026-10-13</strong>. Native Xyce, Xyce/XDM checks, viewer nets/definitions/models, circuit diff, <code>hx netlist net|uses</code>, MCP queries and version 0.5.0 are implemented. HSPICE and Spectre are deferred until their tools are available. See the current dialect matrix for the supported constructs and oracle coverage.</li>
</ol>
<hr />
<h2 id="phase-5--runtime-reserved">Phase 5 — Runtime (reserved)</h2>
<ul>
<li>Not in scope. IR keeps <code>runtime: null</code>. Candidate strategies: C <code>-finstrument-functions</code> / gdb Python / uprobes; SV port probes via <code>verilator --trace</code>; Python <code>sys.setprofile</code>; Rust <code>tracing</code>.</li>
</ul>
</details>

<details>
<summary>Completed core and C/C++ design</summary>
<h2 id="phase-1--core--cc-frontend-done">Phase 1 — Core + C/C++ frontend (done)</h2>
<h3 id="historical-layout-phase-1">Historical layout (Phase 1)</h3>
<pre><code>hx/&#10;  pyproject.toml              # package &quot;hx&quot;, console script &quot;hx&quot;; deps: libclang (+ fastapi/uvicorn from Phase 2)&#10;  hx/&#10;    cli.py                    # hx extract | serve | export | diff | mcp&#10;    api.py                    # extract(...) -&gt; Graph, used by CLI, server and tests&#10;    model.py                  # IR dataclasses + schema version &quot;hx/1&quot;; JSON round-trip&#10;    ids.py                    # stable ID construction + whitespace-insensitive body hashing&#10;    traverse.py               # BFS over a Frontend, depth limit, cycle-safe, exclusion filters, callers&#10;    cache.py                  # per-TU on-disk cache under .hx/cache/ keyed by (path, args) + dep mtimes&#10;    frontends/&#10;      base.py                 # Frontend protocol: locate_entry, function, declaration, type, global_var, callers, stable_id&#10;      clang_fe.py             # libclang implementation (parallel workers, merged USR index)&#10;  tests/&#10;    fixtures/c/               # firmware-style C project; conftest generates compile_commands.json in a temp copy&#10;    test_ids.py  test_traverse.py (fake frontend)  test_clang_fe.py (real libclang)  test_cli.py</code></pre>
<h3 id="historical-ir--graphjson-schema-hx1">Historical IR — <code>graph.json</code>, schema <code>hx/1</code></h3>
<p>This is the Phase 1 shape, retained for context. Current readers/writers use <code>hx/4</code>; see the <a href="../../docs/reference/graph.md">graph reference</a>.</p>
<ul>
<li>Top level: <code>schema</code>, <code>generated</code>, <code>root</code>, <code>lang</code>, <code>entry</code>, <code>meta</code>, <code>nodes{}</code>, <code>types{}</code>, <code>globals{}</code>, <code>edges[]</code>, <code>unresolved[]</code>.</li>
<li><strong>Node</strong>: <code>id</code>, <code>kind</code>, <code>name</code>, <code>qualname</code>, <code>lang</code>, <code>loc{file,line,end_line,col}</code>, <code>signature</code>, <code>storage</code>, <code>depth</code> (negative = caller side), <code>body_hash</code>, <code>precision</code>, <code>returns{type,type_ref}</code>, <code>params[]{name,type,type_ref,dir,dir_source}</code>, <code>globals{reads[],writes[]}</code>, <code>calls[]</code>, <code>runtime: null</code>.</li>
<li><strong>Type</strong>: <code>id</code>, <code>kind</code> (<code>struct|union|class|enum|typedef|…</code>), <code>name</code>, <code>loc</code>, <code>size</code>, <code>align</code>, <code>fields[]{name,type,type_ref,offset,size,bit_offset,bit_width}</code>, <code>enumerators[]</code>, <code>underlying</code>, <code>underlying_ref</code>, <code>anonymous</code>, <code>system</code>, <code>used_by[]</code>.</li>
<li><strong>GlobalVar</strong>: <code>id</code>, <code>name</code>, <code>type</code>, <code>type_ref</code>, <code>loc</code>, <code>storage</code>, <code>scope</code> (<code>file|function-static|member</code>).</li>
<li><strong>Edge</strong>: <code>from</code>, <code>to</code> (null for function-pointer calls), <code>kind</code> (<code>call|macro|fnptr|ref|instance</code>), <code>loc</code>, <code>args[]</code> (as written), <code>name</code>, <code>macro</code>, <code>ptr_type</code>.</li>
<li><strong>Unresolved</strong>: <code>name</code>, <code>from</code>, <code>reason</code>, <code>loc</code>, <code>id</code>.</li>
</ul>
<h3 id="historical-stable-ids-phase-1">Historical stable IDs (Phase 1)</h3>
<p>These examples predate the C/C++ and SystemVerilog identity revisions. Current rules and migration boundaries are in the <a href="../../docs/reference/graph.md">graph reference</a>.</p>
<ul>
<li>Functions <code>c:src/dma.c::dma_start</code>; C++ overloads <code>cpp:src/bus.cpp::Bus::write#a1b2c3d4</code> (hash only on collision).</li>
<li>Types <code>c:include/dma.h::struct dma_chan</code>, typedefs <code>c:include/dma.h::dma_chan_t</code>, anonymous <code>c:include/dma.h::anon@L23</code>.</li>
<li>Globals <code>c:src/dma.c::g_dma_active</code>; function-local statics <code>c:src/main.c::app_run.ch</code>.</li>
<li>Files outside the root keep their absolute path (system headers).</li>
</ul>
<h3 id="traversal-rules">Traversal rules</h3>
<ul>
<li>BFS from entry; <code>--depth N</code> (default 3) or <code>--all</code>; cycles safe; min depth wins; already-expanded callees get an edge without a depth check (recursion is not "beyond depth").</li>
<li><code>--include-callers</code> walks the reverse graph with negative depth; callers' other callees are not expanded.</li>
<li>System headers excluded by default (<code>--include-system</code>); <code>--exclude GLOB</code> repeatable; <code>--max-nodes</code> cap; <code>--type-depth</code> (default 2) limits nested struct expansion while typedef aliases are free.</li>
</ul>
<h3 id="libclang-frontend-facts">libclang frontend facts</h3>
<ul>
<li>Args from compile_commands are sanitized (compiler, <code>-o</code>, dep flags, gcc-only flags dropped; include paths absolutized). Cross compilers (<code>arm-none-eabi-gcc</code>) get <code>--target</code> + their own system include dirs. <code>-resource-dir</code> is injected from <code>clang -print-resource-dir</code> because the pip wheel ships no headers.</li>
<li>Param direction heuristic: by-value → <code>in</code>; pointer/ref/array to const → <code>in</code> (array qualifier is on the array type in libclang); otherwise <code>inout</code>. <code>dir_source: heuristic</code>.</li>
<li>Calls inside macro expansions are detected via <code>MACRO_INSTANTIATION</code> spans and get <code>kind: macro</code> with the macro's spelled args. Function pointers → <code>kind: fnptr</code>, <code>to: null</code>. Address-taken functions → <code>kind: ref</code> and are expanded like callees.</li>
<li>Global reads/writes: writes = assignment LHS, <code>++/--</code>, compound assignment, address taken. Operator kinds come from libclang's C API (<code>clang_getCursorBinaryOperatorKind</code>, LLVM ≥ 17) via ctypes so macro-expanded operators are exact; source-slice fallback otherwise.</li>
<li>Types from system headers are recorded as stubs (no fields) unless <code>--include-system</code>.</li>
</ul>
<h3 id="phase-1-verification">Phase 1 verification</h3>
<ul>
<li>30 pytest cases (fixture layout checked against a gcc-compiled <code>offsetof</code> probe).</li>
<li>Smoke: cJSON (1 TU, 0.14 s); libuv (35 TUs, 0.8 s cold with parallel workers, 0.15 s cached).</li>
</ul>
<hr />
</details>

<details>
<summary>Completed viewer, frontends, diff, and agent integration</summary>
<h2 id="phase-2--viewer--serve">Phase 2 — Viewer + Serve</h2>
<ul>
<li><strong>TLDR</strong>: one <code>viewer.html</code> (vanilla ES modules + vendored Cytoscape.js/dagre, no build step) served by FastAPI; edits persist to <code>annotations.json</code>; SSE live-reload when the graph file changes or a re-extract finishes; <code>hx export</code> emits a standalone HTML with data inlined.</li>
<li><strong>Layout</strong>: left = hierarchy tree (entry → callees by depth, collapsible, search, callers group); center = graph (optional compound nodes grouped by file, dagre layout LR/TB, depth slider, double-click collapses a subtree, hover edge shows call-site args); right = detail (signature, params table with editable <code>dir</code> chip, click type → nested struct/field tree with offsets, source snippet, notes/tags, "verified" checkbox that pins the body hash and flags later changes).</li>
<li>URL hash holds selection/layout so views are linkable. Unresolved calls render as dashed ghost nodes.</li>
<li><strong>API</strong>: <code>GET /api/graph</code>, <code>GET|PUT|PATCH /api/annotations</code> (PATCH = JSON merge patch, <code>null</code> deletes), <code>POST /api/extract</code> (re-run with the args stored in <code>graph.meta</code>), <code>GET /api/source?file&amp;line&amp;span</code> (root-confined), <code>GET /events</code> (SSE: <code>graph</code>, <code>annotations</code>, <code>extract-start</code>, <code>extract-error</code>, <code>ping</code>).</li>
<li><strong>annotations.json</strong> schema <code>hx-ann/1</code>: <code>nodes{id:{note, tags[], verified_body_hash, collapsed, params{name:{dir,note}}}}</code>, <code>types{id:{note, fields{name:{note}}}}</code>, <code>view{hidden[], pinned_positions{}}</code>. Managed graphs share <code>.hx/annotations.json</code> across entry points and snapshots; standalone graphs use adjacent notes unless explicitly overridden.</li>
<li><strong>Export</strong> mode has no server: edits stay in memory and a "download annotations" button yields the file.</li>
</ul>
<h2 id="phase-3--more-frontends-done">Phase 3 — More frontends (done)</h2>
<ul>
<li><strong>TLDR</strong>: two new frontend plugins against the same IR, plus a conformance fixture per language asserting identical invariants.</li>
<li><strong>As built</strong>: <code>hx/frontends/verilator_fe.py</code> and <code>hx/frontends/lsp_fe.py</code>; <code>hx.api.detect_lang</code> picks the frontend by extension (<code>--lang</code> overrides); new CLI flags <code>--sv-file</code>, <code>-f/--filelist</code>, <code>--top</code>, <code>--verilator</code>, <code>--lsp-cmd</code>, <code>--lsp-timeout</code>. IR gained <code>Node.attrs</code> (frontend extras: SV module/specialization/parameters/signals, Rust module path) and <code>DeclRecord.reason</code> (frontend wording for "not expanded").</li>
<li><strong>SV facts</strong>: Verilator lowers enum/struct-typed vars to base vectors in XML; the declared <code>vartype</code> name is used to recover the typedef'd enum/struct. Parameter specializations (<code>core__W10</code>) collapse onto <code>origName</code> for ids; <code>attrs.specialization</code> keeps the real name. Packed struct member LSBs are computed from member widths (first member = MSB). Routine call args and port connections are read from source at the XML <code>loc</code>. One verilator run per extraction, cached by all files Verilator read.</li>
<li><strong>LSP facts</strong>: keys are <code>&lt;uri&gt;#&lt;line&gt;:&lt;char&gt;</code>; everything resolves lazily. Readiness = <code>experimental/serverStatus.quiescent</code> (rust-analyzer) or no <code>$/progress</code> for 0.6 s. Non-function callees (struct/class constructors, enum variants) are reported as unresolved "not a function"; symbols outside the root as "outside project root (library)". <code>typeDefinition</code> results must name a type that appears in the spelled parameter type (guards rust-analyzer jumping through <code>fn</code> aliases). Python field types come from the source annotation, not pyright's narrowed hover. Rust <code>dir</code> = <code>&amp;mut</code> → inout else in (heuristic); Python all <code>in</code> (explicit).</li>
<li><strong>SystemVerilog/Verilog</strong> (<code>verilator_fe.py</code>): <code>verilator --xml-only --xml-output &lt;out&gt; -Wno-fatal &lt;files&gt; [-f list.f] [--top-module X]</code>; <code>&lt;module&gt;</code> → node kind <code>module</code>, <code>&lt;instance&gt;</code> → <code>instance</code> node + <code>instance</code> edge, <code>&lt;var dir=…&gt;</code> → params with <code>dir_source: explicit</code>, <code>&lt;typetable&gt;</code> struct/packed-array dtypes → types with bit ranges, functions/tasks → function nodes. Entry forms: <code>rtl/top.sv:top</code> (module) or <code>top.u_core.alu</code> (instance path).</li>
<li><strong>Generic LSP</strong> (<code>lsp_fe.py</code>): minimal JSON-RPC-over-stdio client; <code>prepareCallHierarchy</code> + <code>callHierarchy/outgoingCalls|incomingCalls</code>, <code>hover</code> (signature text), <code>typeDefinition</code> + <code>documentSymbol</code> (struct fields). Nodes marked <code>precision: lsp</code> (no sizes/offsets). Rust: rust-analyzer (prereq: rustup). Python: pyright-langserver or jedi-language-server; decide at phase start. Rust <code>dir</code>: <code>&amp;T</code> → in, <code>&amp;mut T</code> → inout, owned → in. Python: all <code>in</code> + return.</li>
</ul>
<h2 id="phase-4--diff--agent-integration-done">Phase 4 — Diff + agent integration (done)</h2>
<ul>
<li><strong>TLDR</strong>: the thing the human actually reads after an agent session is <code>hx diff</code> output, ~20 lines.</li>
<li><strong>As built</strong>: <code>hx/diff.py</code> (<code>diff_graphs</code> → <code>hx-diff/1</code> JSON, <code>render_markdown</code>), <code>hx/project.py</code> (<code>.hx/config.toml</code> entries + watch settings, <code>.hx/graphs/&lt;slug&gt;.json</code>, <code>.hx/history/&lt;slug&gt;/&lt;timestamp&gt;-&lt;revision&gt;-&lt;run-id&gt;.json</code> pruned to 20, <code>.hx/last-diff.md</code>, <code>save_extraction()</code>, <code>update()</code>, polling <code>watch()</code>, <code>install_hook()</code>), <code>hx/mcp_server.py</code> (mcp 2.x <code>MCPServer</code>, stdio). CLI: <code>hx track|update|watch|diff|hook|mcp</code>. Server: <code>/api/graphs</code>, <code>?name=</code> on graph-scoped routes, <code>/api/history</code>, <code>/api/diff?since=</code>, <code>POST /api/snapshot</code>; re-extract snapshots the previous graph first. Viewer: graph picker, baseline button, diff selector, green/amber/red classes with text badges, changes list, per-symbol change block, removed functions drawn as red ghosts.</li>
</ul>
<p>Default CLI extraction, updates, MCP, viewer re-extraction, and migration commits use the shared save mechanism. Per-entry current files are authoritative; <code>.hx/graph.json</code> is the latest default CLI selection and follows later saves of that entry. Previous graphs are archived byte-for-byte before replacement, with configured retention; first extraction has no history. Historical files are never overwritten. Thread/process locking and atomic publication protect concurrent writes, and a pending default-copy intent repairs interrupted mirror updates on the next managed save. Explicit CLI <code>-o FILE</code> is standalone output only. <code>meta.provenance</code> version 1 records run ID/times, hx version, actual source Git repository/commit/dirty status, observed dependency hashes, and options/result fingerprints; legacy snapshots retain their original bytes and unknown provenance.</p>
<ul>
<li><strong>Diff identity rules</strong>: nodes/types/globals by stable id; params and fields by name (added/removed/type/dir/offset/size/bits + reordered); edges by (from, to-or-fnptr-name, kind, macro) as multisets, so line drift never registers; equal-count edges with different args → <code>args_changed</code>. Anonymous C types are now named by parent and member (<code>union dma_chan.stat</code>, <code>struct dma_chan.(anon#7)</code>) precisely so a line inserted above them does not churn the diff. System typedefs are summarized, not listed, in Markdown.</li>
<li><strong>Hook</strong>: <code>hx hook print</code> emits a hook configuration for <code>hx update --quiet --hook</code> (300 s timeout). <code>hx hook install --settings-dir &lt;settings-dir&gt;</code> merges it into <code>&lt;settings-dir&gt;/settings.json</code>. Hook mode consumes stdin and always exits successfully so it cannot block the editing workflow.</li>
<li><code>hx diff old.json new.json --format md|json</code>: added/removed nodes; signature changes (param added/removed/type/dir); struct field changes incl. offset shifts; new/removed edges; body changed (body_hash + LOC delta). JSON form drives viewer "diff mode".</li>
<li><code>.hx/config.toml</code>: list of entry points to track. <code>hx watch</code> re-extracts them on file change (debounced), writes <code>.hx/last-diff.md</code>, pushes SSE reload. Editing workflows can also run <code>hx update --quiet --hook</code> automatically after changes.</li>
<li><code>hx mcp</code>: MCP server exposing <code>get_function</code>, <code>callees(id, depth)</code>, <code>callers</code>, <code>get_type</code>, <code>search</code>, <code>diff_since(ts)</code>.</li>
</ul>
</details>

<details>
<summary>Completed hardening and CVA6 / FFmpeg / apragma review fixes</summary>
<h2 id="phase-45--hardening-done">Phase 4.5 — Hardening (done)</h2>
<ul>
<li><strong>TLDR</strong>: an external review of Phase 4 listed eight defects, three tautological tests and overstated docs. Every finding reproduced; all are fixed with regression tests. Terms: tautology = an assertion that cannot fail; merge patch = RFC 7396 JSON update where <code>null</code> deletes; lexer = token splitter.</li>
<li><strong>Verdict table</strong> (finding → root cause → fix):
<ul>
<li>H1 body hash collapsed all whitespace (literals, Python indent) → <code>ids.tokenize(text, lang)</code>: two modes (C-family, Python); literals verbatim, comments dropped, operators by maximal munch, Python indentation relative to the first line. Also found: pyright's call-hierarchy <code>range</code> is only the NAME, so Python bodies were never hashed at all → <code>LspFrontend._full_range</code> (documentSymbol, then indentation/brace scan).</li>
<li>H2 SV module hash = repr(ports, signals, instances with <code>loc</code>) → hash of the <code>module … endmodule</code> source slice (routines likewise), XML-without-locations fallback.</li>
<li>H3 index depended on cache state; <code>include_system</code> absent from the key → summaries merged in TU-path order, the defining TU wins, <code>SUMMARY_VERSION</code> + root + include_system in the cache key, <code>meta.index.variants</code> + a note when TUs disagree.</li>
<li>H4 viewer composed pending patches with <code>mergePatch</code> (drops <code>null</code>) → <code>hx/viewer/patch.js</code> (<code>composePatch</code> keeps deletes, refuses the non-composable delete-then-patch case) and a sequential FIFO of patches; Node unit tests + API delete-persistence test.</li>
<li>H5 overload suffix only on collision; slug collision → C++ ids always carry <code>(param types)</code>; <code>slug = prefix + '-' + hash6</code>, one-time rename of legacy files.</li>
<li>H6 truncation recorded a <code>from</code> outside the graph and dropped the queue; callers skipped globals; type expansion order-dependent → queue carries the parent, <code>truncate()</code> drains it; <code>add_globals</code> in both passes; <code>type_level</code> re-expands with a bigger budget.</li>
<li>H7 params only under signature change, attrs never, edge args only on equal counts → params and attrs always compared; args as multiset difference.</li>
<li>H8 <code>abspath</code> boundary → <code>realpath</code> on both sides.</li>
</ul></li>
<li><strong>Tests</strong>: tautologies removed; conformance runs the invariants under depth 0, type depth 0/99, max-nodes, callers and exclusion, and asserts the caller round trip; new fixtures <code>tests/fixtures/c_variants</code> (build variants) and <code>tests/fixtures/cpp</code> (overloads, template, const method); <code>HX_REQUIRE_TOOLS=1</code> turns every skip into a failure (<code>tests/conftest.py</code>); <code>.github/workflows/ci.yml</code> installs all toolchains on Python 3.10/3.12; <code>tests/test_schema.py</code> validates graphs against <code>hx/schema/hx-1.schema.json</code>.</li>
<li><strong>Docs/packaging/persistence</strong>: base dependencies include <code>tomli</code> (py&lt;3.11), MCP and Pyright with packaged Node.js; extras <code>dev</code> (including <code>jsonschema</code>), <code>e2e</code> and the compatibility <code>mcp</code> extra; README "Boundaries" and optional toolchain install commands; <code>Graph.from_dict</code> enforces the schema major (<code>SchemaError</code>); <code>hx/fsutil.py</code> atomic writes everywhere + <code>flock</code> around annotation read-modify-write; watch also tracks <code>compile_commands.json</code>, <code>Cargo.toml</code>, <code>pyrightconfig.json</code>, <code>CMakeLists.txt</code> even inside skipped build dirs.</li>
<li><strong>Deferred at Phase 4.5 completion (historical)</strong>: Playwright browser workflow tests were added in Phase 4.6; inotify watching and template instantiation expansion remain deferred.</li>
</ul>
<h2 id="phase-46--real-project-hardening-cva6-review-done">Phase 4.6 — Real-project hardening, CVA6 review (done)</h2>
<ul>
<li><strong>TLDR</strong>: a second external review ran hx on CVA6 (403 cells, generate blocks, a parameterized FPU, a 17,270-bit packed configuration parameter). All eleven findings reproduced; the plan went through six review rounds before approval (each round's corrections are recorded in the plan file); everything is fixed with regressions that failed on the previous code. Schema major bumped to <code>hx/2</code>, package 0.3.0. Terms: specialization = one module elaborated with specific parameters; JS-safe integer = below 2^53.</li>
<li><strong>Findings → fixes</strong> (<code>hx/frontends/verilator_fe.py</code> unless noted):
<ul>
<li>H1 wide constants → <code>hx/values.py</code>: ints below 2^53 stay JSON numbers, wider values are canonical hex strings (<code>17270'h…</code> with width, <code>0x…</code> without), x/z keep bit patterns; values are encoded at indexing time so the cache never meets a wide int; <code>hx/graphio.py</code> is the one reader for every consumer (<code>parse_int</code> hook, chunked decimal conversion, no global digit-limit change); signatures show <code>fmt()</code> (<code>CFG=17270'h10000000…0000</code>), the viewer keeps the full literal in a tooltip; <code>diff.py</code> compares values with <code>values.equal</code> and SV signatures by shape.</li>
<li>H2 cache identity → executable resolved before the cache lookup; engine identity = <code>verilator --version</code>; argument files fingerprinted by expanded content (<code>$VAR</code>, <code>${VAR}</code>, <code>$(VAR)</code>) with Verilator's <code>-f</code>/<code>-F</code> nesting rules.</li>
<li>H3 specialized types → module-scoped types are identified by a layout fingerprint (<code>struct fp.fp_t@3f9a1c2e</code>), package types by name; scope-aware named-type recovery; the diff pairs relayouted types through their users.</li>
<li>H4 generated instances → recursive <code>&lt;begin&gt;</code> walk with scope paths; shorthand <code>.clk</code> → <code>.clk(clk)</code>, wildcard → <code>.clk(.*)</code>, XML expression rendering, never <code>…</code>.</li>
<li>H5 viewer layout → root cause isolated by delta debugging INSIDE the viewer (<code>tests/fixtures/viewer/layout-fail.json</code> is the 16-node minimum): dagre throws when a file group mixes a module INSTANCE with that module's own function/task node joined by a call edge (nested compounds + an intra-compound edge across ranks; reproduced with dagre 0.8.5 and 1.1.4 in Node, so no upgrade helps). Element-level fix: in hierarchy graphs a file's functions/tasks get their own group (<code>file · functions</code>); the full CVA6 graph at depth 3 then lays out with the default ranker in ~170 ms, 63 groups intact. Containment kept regardless: retry with the longest-path ranker, then without groups, then breadth-first, notices in the banner; <code>init()</code> never loses selection restore or SSE; <code>window.HX_TEST</code> (lastLayout, ranker, layoutErrors, failLayouts) and <code>window.HX_DEBUG</code> hooks for tests.</li>
<li>H6 anonymous SV types → named by first declaring context (<code>struct top_adv.cfg_i@…</code>), Verilator's <code>__typeimp…</code> names treated as anonymous; no line numbers.</li>
<li>H7 ranges → <code>loc.end_line</code> is the <code>endmodule</code>/<code>endfunction</code>/<code>endtask</code> line; the viewer centres a 120-line window on a distant call site.</li>
<li>H8 warnings → parsed from stderr, stored in the cached index, <code>stats.warnings</code> + <code>warnings_by_tag</code> + a note; the CLI prints errors and warnings apart.</li>
<li>H9 entry file → a module/function must be defined in the file; an instance path's file must define some module on the path.</li>
<li>H10 spelling → <code>__BRA__</code>/<code>__KET__</code>/<code>__DOT__</code>/<code>__0XX</code> decoded everywhere; both spellings accepted on input.</li>
<li>H11 version → <code>hx.__version__</code> is the single source (<code>dynamic</code> in pyproject); 0.3.0.</li>
</ul></li>
<li><strong>Compatibility (R0)</strong>: <code>graphio.load_graph_dict</code> upgrades hx/1 in memory (lossless escape decoding only) and reports what it cannot settle; serve/MCP show <code>migration: pending</code>, the viewer a banner; <code>hx migrate</code> re-extracts every tracked entry into <code>.hx/staging-&lt;pid&gt;</code>, commits only when all succeed (snapshot, atomic move, backup <code>annotations.json.bak-hx1</code> written once, locked rewrite of annotation keys with a <code>meta.migrated</code> marker that <code>normalize()</code> preserves), maps module-scoped types by base id + users and anonymous types by identical layout + users, lists ambiguities and orphans, never guesses.</li>
<li><strong>Fixtures/tests</strong>: <code>tests/fixtures/sv_adv</code> (16,384-bit parameter, two <code>fp_t</code> specializations, generate <code>if</code>/<code>for</code> arrays, shorthand and <code>.*</code> ports, inline struct port, SELRANGE, env-dependent and nested lists), <code>tests/fixtures/legacy/hx1-cva6-like.json</code> (+ annotations), <code>tests/fixtures/viewer/layout-fail.json</code>; <code>tests/test_values.py</code>, <code>test_sv_adv.py</code>, <code>test_migrate.py</code>, <code>test_e2e_viewer.py</code> (Playwright, 7 tests, mandatory in strict mode; CI installs <code>.[dev,e2e]</code> and Chromium). 131 tests, no skips.</li>
<li><strong>CVA6 verification (no <code>PYTHONINTMAXSTRDIGITS</code>)</strong>: depth 0/3/all extract in ~2.5 s; <code>CVA6Cfg</code> is a 17,270-bit literal string, signature 197 chars; 402/402 instance edges with locations, 0 <code>…</code>; <code>gen_instr_scan[0]</code> accepted; 0 <code>__BRA__</code>, 0 <code>anon@L</code>; 61 SELRANGE warnings counted; 403/403 modules with real end lines; <code>fpnew_fma.fp_t</code> → two ids (32 and 64 bits, one user each); wrong entry file → exit 2; <code>TARGET_CFG</code> wt→warm hit→wb miss with <code>gen_cache_wb</code>; comment above <code>core/cva6.sv</code> → zero changes; full graph served at depth 3 → dagre on the first attempt (network-simplex, 63 groups), no page errors, SSE round trip visible in the DOM, <code>CVA6Cfg=17270'h10000000…</code> compact with the full literal in the tooltip.</li>
<li><strong>Known limits</strong>: edges do not avoid nodes; anonymous types that are used nowhere fall back to <code>anon#&lt;hash&gt;</code>; <code>hx migrate</code> handles tracked entries only (ad-hoc <code>.hx/graph.json</code> files are simply re-extracted); template instantiation remains unexpanded for C++.</li>
</ul>
<h2 id="phase-47--review-fixes-ffmpeg-c-review-apragma-python-review">Phase 4.7 — Review fixes (FFmpeg C review, apragma Python review)</h2>
<ul>
<li><strong>TLDR</strong>: two external reviews ran hx 0.3.0 on FFmpeg (309-TU C build) and apragma (Python via Pyright). All nine reported defects reproduced; verifying them surfaced two more. The fixes changed id rules, so the schema is <code>hx/3</code>, <code>SUMMARY_VERSION</code> is 4 and the version 0.4.0. Finding ids are prefixed by review (<code>C-C1</code>, <code>PY-H5</code>) because the apragma review reused the CVA6 review's <code>H</code> numbering. Terms: USR = libclang's symbol string (unique only for external linkage); TU = translation unit; SCC = strongly connected component.</li>
<li><strong>Lexer (<code>hx/ids.py</code>)</strong>: <code>lex(text, lang)</code> keeps spans (<code>Tok(kind, text, start, end)</code>; Python <code>indent</code> tokens are synthetic, <code>start == end</code>); <code>tokenize</code> is its texts, so <code>body_hash</code> is byte-identical (golden test). <code>squash_ws</code> joins tokens with one space per gap (adjacent tokens stay glued; no space after <code>([{</code> or before <code>)]},;</code>), literals verbatim; <code>split_top</code>/<code>paren_span</code>/<code>paren_args</code>/<code>partition_top</code> split only at depth 0, never inside a literal; <code>&lt;</code>/<code>&gt;</code> count as brackets only with <code>angle=True</code> (Rust signatures). Rules per language: Python strings/prefixes/triple quotes and <code>#</code> comments; C string/char/raw literals and both comment forms; Rust lifetimes vs chars and <code>r#"…"#</code>; SV based numbers. Known gaps: Rust closures <code>|a, b|</code> split; nested Rust block comments and PEP 701 nested f-string quotes are not lexed.</li>
<li><strong>C macro arguments (C-C2/C-C3)</strong>: a call expanded from a macro gets its arguments from the recorded invocation span: if the call's extent runs PAST the span the macro produced the callee NAME (<code>FUNCC(x)(args)</code>, object-like <code>av_clip(args)</code>) and the arguments are the list that follows; otherwise (wrapper macro <code>ff_dlog(...)</code>, a call nested in the expansion <code>AV_WB32(a, b)</code> → <code>av_bswap32</code>, a call built from the macro's argument tokens) the arguments are the macro's own. <code>_text</code> uses <code>squash_ws</code>; <code>clean_spelling</code> is for type spellings only. An object-like macro with no following parens gives <code>[]</code>.</li>
<li><strong>C identity (C-C1/C-C4, BufferSinkContext)</strong>: <code>_TUExtractor._key</code> scopes every non-external symbol by the real path of its defining file (<code>usr@/path</code>), extern symbols keep the bare USR (C++ overload hashes unchanged). Types get a provisional key (definition file, else first declaration) plus <code>chain</code>/<code>definition_file</code> provenance; <code>_merge._reconcile_types</code> joins records by union-find over chains (include order no longer matters), keys a class by its single definition file, keeps definition-less classes incomplete, and refuses to merge a class with several definition files (stubs stay incomplete, note). Variants: each TU's view is fingerprinted by <code>ids.fingerprint_types</code> (Tarjan SCCs, dependencies first, canonical member order by qualified identity, internal edges by index, external by fingerprint, one hash per component); a class with several fingerprints among complete views splits into <code>key|&lt;8hex&gt;</code> / id <code>…@&lt;8hex&gt;</code>; a TU that only saw a declaration borrows the unique complete view, else refers to the plain incomplete key. Typedef shapes exclude size/align (they belong to the target). File identity is <code>realpath</code> everywhere (<code>ids.rel</code>, <code>_same_file</code>, <code>locate_entry</code>, cache key).</li>
<li><strong>LSP (PY-H1…H5, overloads)</strong>: <code>CONTAINER_KINDS</code> includes functions/methods, so nested functions are <code>outer.inner</code> and qualified entries resolve; <code>_scope_path</code> falls back to <code>detail</code> (<code>class X (file)</code>) because Pyright's documentSymbol lists only the last <code>@overload</code>; <code>_register</code> keeps <code>#hash</code> only for residual collisions. <code>function()</code> memoises records and hands out copies; module callers (kind 2) are <code>module</code> nodes spanning the file, hashed over the file; outgoing calls are skipped for Python modules only (all 12,638 recorded requests were empty). Members of a VERIFIED stub overload family (<code>.pyi</code> or library file, <code>@overload</code> above the declaration, known scope: class path or confirmed <code>&lt;module&gt;</code>) collapse to one target with <code>family {size, evidence, scope}</code> on the unresolved record; unknown scope never collapses. Methods arriving as kind 12 are recognised through <code>detail</code>. In-root <code>.pyi</code> declarations are <code>has_definition=False</code> ("stub declaration").</li>
<li><strong>Traversal (PY-H4)</strong>: <code>callers()</code> decides admission from <code>declaration()</code> first, then the existing graph node, then the node cap, and fetches <code>function()</code> only for a caller that enters the graph; <code>calls</code> is appended on the graph node under the existing membership guard.</li>
<li><strong>Schema hx/3 and migration</strong>: <code>graphio.MIGRATIONS</code> chains <code>migrate_1_to_2</code> (stamps <code>hx/2</code>) and <code>migrate_2_to_3</code> (stamps <code>hx/3</code>; lists hashed LSP ids, module-callers-as-functions, hash-less nested functions by extent containment, absolute-path C ids, and flags every LSP graph conservatively). <code>project.map_node_ids</code> maps by (file, kind, name, line) with old absolute files made relative, module nodes and nested names (dotted suffix); <code>map_ghost_ids</code> maps unresolved ids by call site with identity checks and requires <code>family</code> evidence for hashed or many-to-one mappings; <code>map_type_ids(old, new, candidates, user_map)</code> takes every old type id absent from the new graph. <code>migrate_file</code> takes <code>from_schema</code>/<code>backup_suffix</code>/<code>invalidate</code> (module nodes lose <code>verified_body_hash</code>). History snapshots keep old ids: the first <code>update</code> after a migration shows a one-time removed/added churn.</li>
<li><strong>Review bundles</strong>: both replays take <code>--hx-src PATH --mode fixed</code> (env <code>HX_REVIEW_HX_SRC</code>, <code>HX_REVIEW_MODE</code>), record every stage's exit code in <code>replay-results.json</code>, stop at the first failure with a non-zero exit, accept <code>--fail-stage</code> as a self-test, and ship the curated exception lists (<code>checks/macro-exceptions.json</code>, <code>probes/argument-exceptions.json</code>: zero UNEXPECTED mismatches, listed entries need a class and reason, stale entries fail). The apragma oracle takes argument boundaries from the call's own tokens (stdlib <code>tokenize</code>, comments/layout dropped, strings verbatim); the FFmpeg oracle applies the name-generating-macro rule only in fixed mode so defect-mode counts stay reproducible.</li>
<li><strong>Rounds 9–11 (2026-10-13), C identity refined on FFmpeg</strong>: (1) a type local to a function is qualified by it (<code>f::local</code>, C and C++; file-scope C tags stay bare), and two distinct types that would still share one public id (the same tag in two blocks of one function, two anonymous types on one line) keep both with a documented position-dependent <code>#hash</code> and a note — never a silently dropped layout. (2) The declaration chain records every file that declares OR names the type at file scope in the TU (forward declarations, definitions, typedef targets, field types, prototype parameters, globals' types), because libclang reports <code>typedef struct x x;</code> after an earlier <code>struct x;</code> as a reference and FFmpeg forward-declares its opaque types in several headers; a declaration-only class is keyed by the file every member TU saw, else the first in path order, and its record's <code>loc</code> moves to that file's first mention. (3) Typedefs group by name (a redeclared typedef's USR carries whichever header a TU read first, like a tag's canonical declaration) and merge only when every redeclaration names one target identity; otherwise each keeps its own key. (4) Borrowing of the unique complete view is WITHIN a reconciled class only, never across classes by raw USR (that made variant hashes depend on unrelated TUs); a stub is fingerprinted as <code>["incomplete", kind, qualname, class file]</code> — never the raw USR (a local type's USR carries a byte offset) and never a file-free form (two unrelated <code>struct x;</code> stay two identities) — and a complete record's identity file is its class's, not its own declaration's. <code>SUMMARY_VERSION</code> 5. Measured on FFmpeg: 1,278 types, 4 variant classes (the <code>TXSample</code>/<code>TXComplex</code>/<code>AVTXContext</code> build-flag family, listed by hand in <code>checks/variant-classes.json</code>), no id collision, index 16.6 s (was 15.6 s); the literal "restrict borrowing" alone had given 48 classes, declarations-only chains 22 with <code>AVCodecContext</code> split five ways by identical layouts.</li>
<li><strong>Rounds 9–11, migration and traversal</strong>: <code>map_ghost_ids</code> reads every reference (unresolved records AND edges), requires every call site of an old ghost to yield the same single compatible target (a site without one → unmapped, disagreeing sites → ambiguous), has no shortcut for an unchanged id (a site that still references the id itself is an exact answer there), and the family rule also requires <code>family.scope</code> to equal the target's scope. Nodes use <code>_scope_compatible_node</code> (an already-qualified old name may gain enclosing-function scopes: <code>Device._interp_with</code> → <code>Device.evaluate._interp_with</code>); ghosts keep the strict rule (equal, or bare → scoped). <code>migrate()</code> invalidates <code>verified_body_hash</code> by meaning (<code>_invalidated_ids</code>: the old node was a <code>(module)</code> function, or the kind changed), not by an id change — a module node's id is unchanged across hx/2 → hx/3. The apragma bundle carries <code>test_oracle.py</code> (stdlib-only self-test of the call-argument oracle) as a replay stage in both modes. The venv's Pyright launchers had to be reinstalled (their shebangs named a deleted path; the suite had passed through a conda copy on PATH).</li>
<li><strong>Fixtures/tests</strong>: <code>tests/fixtures/c_macros</code>, <code>c_scoped</code> (same-basename statics, reversed include orders, shared forward declaration with two definitions, shared typedef and wrapper over variant targets, <code>#ifdef</code> layouts and enums, mutual recursion, opaque handle, private pairs; rounds 9–11: function-local types <code>l.c</code>, second forward declaration <code>fwd2.h</code>/<code>t4.c</code>/<code>t5.c</code>, wrapper over the opaque handle <code>hbox.h</code>, shared typedef over two opaque declarations <code>a_opaque.h</code>/<code>b_opaque.h</code>/<code>opq.h</code>, truly disconnected <code>c_opaque.h</code>/<code>d_opaque.h</code>, local stub under a conditional layout <code>lf.h</code>, redeclared typedef <code>ctx_a.h</code>/<code>ctx_b.h</code>), <code>cpp_rec</code> (<code>A::node</code>/<code>B::node</code>, local classes <code>local.cpp</code>), <code>python/hxfix/{nested,script,ovl}.py</code>, <code>python/fakelib</code> stub package, <code>legacy/hx2-apragma-*.json</code> and <code>hx3-apragma-device-evaluate.json</code> (saved experiment graphs), <code>viewer/py-module.json</code>; <code>tests/test_lex.py</code>, <code>test_clang_macros.py</code>, <code>test_clang_scoped.py</code> (with <code>_gcc_run</code>, a generated <code>main</code> that calls fixture functions, since <code>sizeof</code> in <code>main</code> cannot see a local type), <code>test_migrate_hx3.py</code> and additions to <code>test_traverse.py</code>, <code>test_lsp_fe.py</code>, <code>test_e2e_viewer.py</code>.</li>
</ul>
</details>

<details>
<summary>Completed SPICE/ngspice implementation and review fixes</summary>
<h2 id="phase-n1--circuit-netlists-spice--ngspice-done">Phase N1 — Circuit netlists: SPICE + ngspice (done)</h2>
<ul>
<li><strong>TLDR</strong> (historical: hx/3 was current when N1 shipped; graphs are hx/4 since 0.5.0, see the 0.5.0 section): <code>hx extract deck.sp:.</code> yields an hx/3 graph of a SPICE-family deck (deck <code>module</code> → <code>X</code> <code>instance</code> nodes → primitive <code>device</code> nodes, hierarchy as <code>instance</code> edges with nets as written) plus an additive <code>circuit</code> block (scoped declarations with status, nets with bindings, terminal→net and port→net tables, directives, verbatim control blocks, probes, diagnostics). Viewer, diff, track, watch, export and MCP reuse the existing machinery. Simulators are optional oracles only; a missing one is named with its install command. Plan: <code>~/.claude/plans/review-the-experiment-results-valiant-thunder.md</code> (15 review rounds). Terms: deck = top-level netlist file; subckt = <code>.subckt</code> definition; occurrence = one instance or device at one path under one guard; guard = the set of enclosing <code>.if</code> constraints; oracle = a simulator run only to cross-check structure; profile = dialect data table; grammar = the statement syntax family a profile selects.</li>
<li><strong>Layout</strong>: <code>hx/netlist/profiles.py</code> (data only: <code>Family</code>, <code>Directive</code>, <code>Profile</code>; <code>SPICE</code>, <code>NGSPICE = replace(SPICE, inline_comment=("$", ";", "//"), directives += .if/.elseif/.else/.endif/.control/.endc/.csparam)</code>; <code>sniff_dialect</code>), <code>names.py</code> (folding, escapes, paths, canonical conditions, guard ids), <code>lexer.py</code> (statements with per-piece spans; <code>+</code> continuation joins across comment AND blank lines, as ngspice does; verbatim <code>.control…​.endc</code> and <code>.prot…​.unprot</code>; stops at <code>.end</code>), <code>parser.py</code> (<code>lex_file</code> → role-free <code>RawFile</code> cached; <code>structure(raw, role, profile)</code> applies the title rule before grouping: a deck's statement 1 is the title whatever it says, an include keeps line 1), <code>grammar.py</code> (<code>SpiceGrammar.split_element</code> locates the optional/required model token by scope lookup within the family's arity range; <code>split_definition</code>), <code>index.py</code> (<code>DesignIndex</code>: files, scoped <code>decls[(kind, scope, name)]</code>, guards, <code>resolution</code>, <code>probes</code>, <code>deps</code>, <code>lookup</code> with alternatives/ambiguous/bins, hashes), <code>resolve.py</code> (<code>Elaborator</code>: children memoised per occurrence, instances, devices, nets, references, <code>MAX_HIER_DEPTH = 64</code>), <code>hashing.py</code>, <code>oracle.py</code> (closure render, listing parser, name forms, projection, comparison), <code>check.py</code> (<code>check_ngspice</code> → report, exit 0/1/2), <code>hx/tools.py</code> (registry: ngspice, xyce, xdm, spectre, hspice; <code>find_tool</code>/<code>resolve_tool</code>: override → env → PATH → fallbacks; an explicit override never falls back), <code>hx/frontends/spice_fe.py</code> (<code>SpiceFrontend</code>, lang <code>sp</code>, <code>finalize(graph)</code> attaches <code>circuit</code>, <code>meta.deps</code>, <code>meta.probes</code>), <code>hx/traverse.py</code> calls the duck-typed <code>finalize</code>. CLI: <code>extract --dialect/--deck/--search-path</code> (tracked), <code>hx netlist check ENTRY --oracle ngspice [--ngspice PATH] [--json] [--limit] [--timeout]</code>; <code>project.dependency_files</code> + <code>source_signature(extra)</code> with a <code>MISSING</code> sentinel feed <code>hx watch</code>; <code>TUCache.deps_fresh</code> accepts <code>None</code> = "must still be absent"; MCP <code>extract</code> merges tracked options with explicit overrides (<code>None</code> = omitted) for every language.</li>
<li><strong>Contracts</strong>: ids <code>sp:&lt;deck&gt;::(deck) &lt;basename&gt;</code>, <code>sp:&lt;deck&gt;::xdut.m1</code>, definition views <code>sp:&lt;def file&gt;::@opamp[.m1]</code>, guarded occurrences <code>#&lt;guard_id&gt;</code> (constraint-derived, never positional; identical-chain duplicates <code>guarded-duplicate</code> with a position hash); nets are not nodes (<code>circuit.nets</code>, keys <code>scope.name</code>, ground <code>0</code>, globals bare, <code>.global</code> nets as <code>GlobalVar</code> reads); device <code>params</code> = terminals (<code>type: terminal</code>, <code>dir_source: explicit</code>), instance <code>params</code> = definition ports (heuristic); <code>Guard = frozenset[(chain_id, branch)]</code>, <code>chain_id = (scope, canonical conditions)</code>, compatible = no shared chain with different branches, lookup stops at the first scope with a visible declaration, exclusive guards → <code>alternatives</code>, compatible → <code>ambiguous</code>; a definition's hash covers its header (ports, defaults) and body, so a port-order edit moves it; diagnostics of a library file count only inside the sections a <code>.lib</code> reference selects; a library section pulling sibling sections of its own file is not a cycle (cycles key on file + section); <code>.ends othername</code> closes the subckt with <code>ends-name-mismatch</code>; <code>N</code> = OSDI (compiled Verilog-A) devices with positional terminals <code>t1…</code>.</li>
<li><strong>Oracle facts (ngspice 45.2, X11 build)</strong>: batch mode reads the deck from stdin (<code>ngspice -n -b &lt; deck</code>; never <code>/dev/stdin</code>); <code>listing expand</code> rows <code>&lt;line&gt; : &lt;name&gt; &lt;nets…&gt; &lt;model|value&gt;</code> lower-cased, line 1 is the title whatever it says, <code>.model</code> cards anywhere, only the active <code>.if</code> branch listed, a local model as <code>xa:dmod</code>, nested names by declaration context (<code>c.xa.c.xh.c1</code> local wrap, <code>r.xb.xh.r1</code> global chain, <code>r.xo.xm.xg.r.xl.r1</code>), <code>PARAMS:</code> and trailing <code>//</code> accepted, <code>Q</code> with 3 or 4 terminals, a guarded <code>F</code> sees an unconditional <code>V</code>, <code>ln</code> is a function name (not usable as a parameter), continuations join across blank and comment lines, <code>.ends</code> ignores its name, a section may <code>.lib</code> sibling sections of its own file. Hence: hx feeds its rendered closure (includes and selected sections inlined, every <code>.control</code> removed, <code>.end</code> dropped, then <code>listing expand</code>), compares unguarded devices only (guarded ones and the rows they could spell are counted), compares arity by family grammar never by numeric tokens, strips the <code>&lt;inst&gt;:</code> model prefix and checks scope, reports a tolerant name match as <code>name-form</code>, and calls an unsimulatable deck "oracle unavailable" (exit 2, first simulator error quoted).</li>
<li><strong>Coverage run</strong> (<code>dev/scripts/netlist_coverage.py</code>, artifacts <code>~/hx-review-artifacts/netlists/apragma-20261013/</code>): the apragma decks are mirrored into <code>&lt;out&gt;/apragma-mirror</code> with <code>models</code> symlinked so the apragma checkout is never written to; thresholds: 0 <code>unparsed-statement</code> and 0 <code>unknown-device-family</code> on the three apragma examples, the numeric GF180 sample agrees with ngspice with 0 mismatches (the raw deck's exit 0 confirmed first), the symbolic template is "oracle unavailable", the sky130 <code>tt</code> wrapper extracts cold ≤ 30 s and warm ≤ 3 s from the cache with a nonzero declaration count and a definition view of <code>sky130_fd_pr__nfet_01v8</code>. The first run found four parser gaps on the GF180 library (sibling-section cycles, continuations after blank lines, mismatched <code>.ends</code>, diagnostics from unselected sections) and the OSDI <code>N</code> letter on the IHP library; all fixed with fixtures <code>pdk/</code> and <code>osdi/</code>.</li>
<li><strong>Fixtures/tests</strong>: <code>tests/fixtures/spice/{ota, ota_rewired_lib, scoped, title, params, bjt, numeric_nets, bins, conditional, globals, shared, oracle/search_path, fail, pdk, osdi}</code>, <code>tests/fixtures/viewer/spice-ota.json</code>; <code>tests/test_netlist_{lexer,parser,index,resolve,hash,oracle}.py</code>, <code>test_spice_fe.py</code>, additions to <code>test_conformance.py</code> (<code>_check_circuit</code>), <code>test_diff.py</code>, <code>test_cli_langs.py</code>, <code>test_project.py</code>, <code>test_schema.py</code>, <code>test_mcp.py</code>, <code>test_e2e_viewer.py</code>; <code>tests/conftest.py</code> <code>vendor_tool</code> marker with <code>HX_REQUIRE_VENDOR_TOOLS</code>.</li>
<li><strong>Review fixes 1.1 (2026-10-14; critique of N1 reviewed three rounds, every item reproduced before planning)</strong> (fixtures named below: <code>conditional/shared_include.sp</code> includes <code>conditional/shared.inc</code>): (1) <code>Elaborator.canonical(key, occ)</code> follows port bindings along the occurrence's own ancestor chain (<code>_by_key</code> registry); a net with several bindings and no ancestor among them stops (nothing guessed); <code>terminals[].canonical</code> added; <code>hx diff</code> compares IMMEDIATE bindings (device terminal keys, instance <code>ports[].outer</code>), so an ancestor's rewiring is reported once. (2) <code>circuit</code> declaration records merge across calls (<code>_merge_record</code>, dedupe by <code>(identity, file, line)</code>: two unguarded cards of one name share an identity, one file included from <code>.if</code> and <code>.else</code> shares a source) and <code>finalize</code> also walks unresolved ghosts: an ambiguous instance lists its candidates (<code>ambiguous</code>), a missing one a <code>missing</code> record, bodies unexpanded; <code>terminals</code>/<code>ports</code> stay node-keyed, <code>instances</code>/<code>used_by</code> may name ghosts. (3) Controlling references keep every guard-compatible target (<code>refs[].targets</code>, <code>attrs.controls[].targets</code>, one <code>ref</code> edge each; a ghost for a missing one); compatible targets → <code>ambiguous-reference</code>; the oracle takes the name form from the first target or the spelled name. (4) Grammar order terminals → refs → model → value (<code>W1 out 0 VSENSE sm</code> keeps <code>sm</code>); <code>compare</code> never skips a required-model family (a <code>None</code> model on either side is a <code>model</code> mismatch); <code>subtree</code> filters hx devices too (<code>out_of_scope_hx</code>). (5) Scope hashes carry each statement's guard key (<code>item_texts</code> → <code>(guard, text)</code>), so a condition-only edit moves the deck's and the definitions' hashes while spacing does not. (6) Deck role: <code>DesignIndex(deck_role)</code>, <code>SpiceFrontend(deck_role="deck|library|auto")</code>; <code>api.extract</code> passes <code>auto</code> for <code>@</code> entries without <code>--deck</code> (line 1 a dot-directive → library, read like an include with diagnostics), stores <code>extract_args.deck</code> AS GIVEN (<code>None</code> when omitted, so the viewer's <code>POST /api/extract</code> and <code>project.update</code> replay the library reading), <code>meta.index.deck_role</code>, <code>circuit.root.deck_role</code>; a deck title starting with <code>.</code> gets <code>title-is-directive</code>. (7) <code>names.canonical_expr</code> normalises an expression token's interior (whitespace, case) keeping delimiters and inner <code>"…"</code> strings. (8) <code>check_ngspice</code> compares a definition-rooted entry with deck context once per unguarded instance (<code>SpiceFrontend.instances_of</code>, deck extracted once, ngspice run once, <code>compare(..., subtree=P)</code> per instance, per-instance report lines); no unguarded instance → unavailable before the simulator starts; a library reading without <code>--deck</code> → "no deck context … pass --deck". New fixtures <code>conditional/{nested_guard, per_branch, ref_alternatives, shared_include(.sp/.inc)}</code>, <code>fail/{ref_duplicate_and_missing, duplicate_model}</code>, <code>switches/switches.sp</code>, <code>oracle/uninstantiated.sp</code>; conformance invariants: every <code>definition_refs</code>/<code>model_refs</code> key serialised, every ambiguous/missing instance ghost listed, canonical ports equal the chain walk, unique reference targets with a diagnostic on overlap; <code>_spice_nested</code> factory. Known limit: <code>diff._decl_hashes</code> keys by identity, so a same-identity ambiguous pair diffs as one key (already an error).</li>
<li><strong>Known limits (N2–N5)</strong> (historical, as of 2026-10-14; the Xyce profile, <code>Y</code> devices, <code>.func</code>/<code>.measure</code>, net highlighting, the nets/definitions panes, <code>hx netlist net|uses</code> and the Xyce/XDM checks shipped in 0.5.0, see that section; still open: HSPICE/Spectre, numeric bin selection, <code>A</code> devices, <code>.alter</code>): HSPICE/Xyce/Spectre profiles; numeric bin selection; <code>Y</code>/<code>A</code> devices, <code>.alter</code>, <code>.func</code>, <code>.measure</code>; net highlighting, nets/definitions panes and <code>hx netlist net|uses</code>; Xyce/XDM oracles; ids outside the root are absolute; the oracle needs numeric parameters.</li>
</ul>
</details>

<details>
<summary>Completed Rust/Xyce 0.5.0 hardening and acceptance design</summary>
<h2 id="rust-and-xyce-hardening--050">Rust and Xyce hardening — 0.5.0</h2>
<ul>
<li><strong>Rust identities and source boundaries.</strong> rust-analyzer remains the semantic authority. UTF-8/UTF-16 positions, qualified entries, trait arguments, closures, nested comments and long calls are handled explicitly. Source-backed Rust IDs never acquire positional collision suffixes; generated targets without a source declaration remain unresolved. Caller-only records avoid unrelated outgoing queries. Request counts/times and readiness failures are recorded.</li>
<li><strong>Compatibility.</strong> Schema <code>hx/4</code> changes Rust identity/token rules. Old readers upgrade through the 1→2→3→4 chain in memory. Rust graphs request re-extraction; persistent migration maps annotations with source evidence, retains backups and history, reports ambiguities and invalidates changed verification hashes.</li>
<li><strong>Native Xyce.</strong> A local 7.10 registration inventory describes 64 family names and 117 level descriptors. Native grammar covers named Y devices, U selectors, multi-inductor references, model-level terminal bounds, global parameters, functions and data blocks. Unsupported constructs retain diagnostics. The inventory describes structural coverage, not simulator validation of every level.</li>
<li><strong>Independent checks.</strong> Xyce checks mirrored original decks for syntax/topology, normalized family counts and exposed net names. XDM checks its exposed top-level primitive inventory. Translation warnings or missing U devices are unavailable, never agreement; nested inventory, terminal bindings and model values remain outside that XDM interface. HSPICE and Spectre remain deferred.</li>
<li><strong>Review workflow.</strong> Saved-graph <code>hx netlist net|uses</code> and MCP <code>get_net</code> / <code>netlist_uses</code> report aliases, canonical connectivity, guarded alternatives and declaration users, with bounded results. Nets, Definitions and Models viewer panes support navigation and highlight connected devices along hierarchy paths. Circuit changes have a dedicated section with retained before/after records, including removed declarations; exports carry the same behavior.</li>
<li><strong>Acceptance.</strong> <code>dev/scripts/hardening_coverage.py</code> pins Codex revision <code>221e4e7c05386d06aa7b91da2a9b04f7f2bd921f</code> and Rust 1.95.0. Eight entries run with depth 0, depth 2 and callers in forward/reverse fresh analyzer sessions. A development-only syn parser checks argument boundaries; macro-body gaps must have independent span evidence, while unexpected gaps and mismatches fail. The Xyce/XDM fixture manifest pins unavailable-check reasons. Normal CI uses reduced fixtures; the production runner is explicit and retains JSON/Markdown reports, tool versions, source fingerprint, timings and request counts.</li>
</ul>
</details>

## Status log

<details>
<summary>Dated implementation, validation, and planning record (2026-10-09–2026-10-23)</summary>
<ul>
<li><strong>2026-10-09</strong> — Plan approved. Phase 1 implemented and verified (30 tests; cJSON, libuv smoke). Additions vs. original plan: top-level <code>globals{}</code> table, edge kind <code>ref</code>, operator kinds via libclang C API. Viewer tech adjusted from "TypeScript via esbuild" to vanilla ES modules + vendored libraries so there is no build step.</li>
<li><strong>2026-10-09</strong> — Phase 2 done. <code>hx serve</code> (FastAPI + uvicorn, lifespan watcher polling graph/annotations mtimes, SSE), <code>hx export</code>, <code>hx/annotations.py</code> (merge patch, recursive prune), viewer in <code>hx/viewer/</code> (vanilla JS, Cytoscape 3.34.3 + dagre 0.8.5 vendored). 42 tests (SSE tests run a real uvicorn thread because Starlette's TestClient buffers whole responses). Verified with headless Chrome screenshots in light and dark mode, console clean. Viewer extras beyond plan: <code>?theme=</code>, <code>?live=0</code>, caller side in tree, per-reason unresolved groups, global read/write panel, edge detail page.</li>
<li><strong>2026-10-09</strong> — Phase 3 done. SystemVerilog (verilator 5.020), Rust (rust-analyzer 1.99, installed via rustup <code>--profile minimal --no-modify-path</code>, binaries in <code>~/.cargo/bin</code>) and Python (pyright 1.1.414 via pip) frontends; fixtures under <code>tests/fixtures/{sv,rust,python}</code>; 62 tests green including a cross-frontend conformance test; viewer shows instance edges, bit-sized HDL layouts and node attrs (verified by headless Chrome).</li>
<li><strong>2026-10-09</strong> — Phase 4 done. <code>hx diff</code>, tracked entries with snapshots/history, <code>hx update</code>/<code>hx watch</code>, update hook installer, viewer diff mode and graph picker, MCP server (mcp 2.3.0). 76 tests green. Verified end to end on the C fixture (last-diff.md and viewer diff screenshot) and MCP tools through the in-memory client.</li>
<li><strong>Open items at Phase 4 completion (historical)</strong>: browser workflow tests and the reserved <code>annotations.view.hidden</code> UI were still pending then; both were implemented on 2026-10-10 (see Phase 4.6 and the hide/show entry below). Export mode keeps edits in memory until downloaded; LSP frontends have no on-disk cache (the historical fixture runs took ~2–4 s per extraction); SV internal-signal reads/writes per always block are not extracted (signals are listed in <code>attrs</code> only); Go profile (<code>gopls</code>) exists but is untested; <code>hx watch</code> polls (no inotify); MCP <code>extract</code> tool is synchronous; Phase 5 (runtime capture) remains reserved.</li>
<li><strong>2026-10-09</strong> — Dependency installation follow-up: MCP and Pyright with its packaged Node.js runtime now install with the base package; Python 3.10 retains its conditional <code>tomli</code> dependency. Preserved the compatibility <code>mcp</code> extra and documented developer/browser extras plus optional language toolchains. CI checks base installation before developer dependencies on Python 3.10/3.12. Verified clean wheel installs, dependency consistency and Pyright without system Node on both Python versions; 97 tests passed on each with no skips, plus all 4 standalone JavaScript tests.</li>
<li><strong>2026-10-10</strong> — Phase 4.5 (hardening) done. External review verified line by line (8/8 findings reproduced, plus one worse than reported: pyright body hashes covered only the function name). Token-based <code>body_hash(text, lang)</code>, SV source-slice hashes, deterministic cache merge with complete keys, viewer patch FIFO with <code>composePatch</code>, C++ parameter-list ids, hashed slugs with legacy migration, traversal truncation/caller-globals/type-order fixes, broader diff, realpath confinement, JSON schema + loader check, atomic writes + file lock, CI workflow with <code>HX_REQUIRE_TOOLS=1</code>. Version bumped to 0.2.0 (cache <code>SUMMARY_VERSION</code> 2 invalidates old <code>.hx/cache</code>).</li>
<li><strong>2026-10-10</strong> — Viewer edges switched from bezier to orthogonal routing (<code>curve-style: round-taxi</code>, 8px corner radius, direction follows the layout, turn 22px after the source so the cross run stays in the inter-rank gap, parallel edges staggered by 10px via <code>data.pi</code>, self-loops stay bezier). Taxi edges do not avoid obstacles; that is a known limit. Verified by headless screenshots in both layouts.</li>
<li><strong>2026-10-10</strong> — Phase 4.6 done (CVA6 review, 11 findings; plan reviewed six rounds). hx/values + hx/graphio, schema hx/2 + <code>hx migrate</code>, SV frontend rewrite (generate scopes, layout-identified types, context-named anonymous types, real ranges, warnings, entry validation, cache identity), viewer layout fallbacks with the minimized CVA6 reproducer, Playwright browser tests. 131 tests green in strict mode; every reviewer reproduction re-run on CVA6 without the digit-limit workaround. Version 0.3.0. Not committed (user commits).</li>
<li><strong>2026-10-10</strong> — Viewer: hide/show modules (eye on tree rows, detail-pane button, <code>h</code>). Hidden nodes are walls in <code>visibleSet()</code>: the node, its edges and everything only reachable through it disappear; shared routines stay. State in <code>annotations.view.hidden</code> (the slot reserved since Phase 2), so it persists, migrates with ids and carries into exports. Four Playwright tests (C fixture, export page, SV subtree).</li>
<li><strong>2026-10-12</strong> — Phase 4.7 done (FFmpeg C review C-C1…C4, apragma Python review PY-H1…H5, plus the struct-tag USR collision and the Pyright overload fan-out found while verifying; plan reviewed eight rounds). Lexer with spans (<code>ids.lex</code>, golden body hashes), literal-aware splitters, macro-argument rule, file-scoped C identity with cross-TU type reconciliation (chains, union-find, SCC fingerprints, borrowing of the unique complete view for fingerprinting only, canonicalised edge targets), nested LSP qualnames, memoised records, module nodes, caller admission before fetch, verified stub overload families, schema hx/3 with the 1→2→3 chain and location/call-site/user-based migration, both review bundles replayable against a fixed checkout with mirrored fixed-mode audits and <code>--fail-stage</code> self-tests. 175 tests green in strict mode. FFmpeg fixed replay: 309/309 TUs, 7,017 functions (the two discarded statics are back), 73 graphs valid, 5 layouts/26 fields match GCC, 9,199 macro call sites compared with 0 mismatches (was 1,259), four distinct static ids, symlink spelling gives the same ids, defect audit fails exactly its 5 "reproduced" checks, fixed audit 24/24. apragma fixed replay: 925/925 source calls matched with 0 identity differences (was 181), 0 call-argument mismatches under the token oracle (was 494), <code>Device.evaluate</code> callers 25 s / 1,660 requests / 26 outgoing-call fetches (was 100.8 s / 28,963 / 13,615), module caller node lines 1–301 whose hash moves on the <code>VDD</code> edit, nine <code>save_ds_data</code> parameters, fixed audit 16/16. Version 0.4.0, <code>SUMMARY_VERSION</code> 4. Not committed (user commits).</li>
<li><strong>2026-10-13</strong> — Phase 4.7 review rounds 9–11 done (plan reviewed eleven rounds in all). Function-local types qualified by their function with a documented <code>#hash</code> for residual collisions; declaration chains over every file that declares or names a tag (typedef targets, fields, prototypes, globals), declaration-only classes keyed by the file every TU saw, redeclared typedefs grouped by name and merged when their targets agree; borrowing within the reconciled class only, stub fingerprints by qualified identity plus class file, complete-record identities by class file; <code>SUMMARY_VERSION</code> 5. Ghost migration reads edges and records, requires every call site to agree, has no unchanged-id shortcut and checks <code>family.scope</code>; nodes get the prefix rule, ghosts keep the strict one; module verification is invalidated by meaning. 186 tests green in strict mode (venv Pyright launchers reinstalled; <code>PATH</code> must put <code>.venv/bin</code> first). FFmpeg fixed replay re-run from scratch: 309/309 TUs, 7,017 functions, 1,278 types, index 16.6 s, 9,199 macro call sites compared with 0 unexpected mismatches, 4 variant classes (all the TX build-flag family, hand-listed in <code>checks/variant-classes.json</code>), no type-id collision, every stage at exit 0 with the defect audit tolerated (it fails exactly its 5 reproduced checks), fixed audit 26/26, <code>--fail-stage</code> self-test exits 1. apragma fixed replay re-run from scratch: 13 stages at exit 0 including the new <code>test_oracle.py</code> stage and the audit inside the replay, 925/925 source calls matched with 0 identity differences, 0 unexpected argument mismatches, <code>Device.evaluate</code> callers 25.9 s / 1,660 requests / 26 outgoing-call fetches, module caller node lines 1–301, fixed audit 16/16, self-test exits 1. In-memory probes before adoption: the literal "restrict borrowing" rule alone gave 48 FFmpeg variant classes, declaration-only chains 22 (<code>AVCodecContext</code> split five ways by identical layouts), the adopted rules 4. Not committed (user commits).</li>
<li><strong>2026-10-13</strong> — Phase N1 done (circuit netlists: SPICE + ngspice end to end; plan reviewed fifteen rounds). Native parser under <code>hx/netlist/</code> with data-only dialect profiles, scoped guard-aware lookup, include/library closure with probes, the <code>circuit</code> block (schema hx/3, additive), <code>sp:</code> ids owned by the deck with definition-rooted views, device/instance nodes in viewer, diff (wiring, models, definitions, params), track/watch over dependencies and probes, MCP <code>extract</code> option merging, the optional-tool registry (<code>hx/tools.py</code>) and <code>hx netlist check --oracle ngspice</code>. Coverage run (<code>~/hx-review-artifacts/netlists/apragma-20261013/</code>): the three apragma decks parse with 0 unparsed statements and 0 unknown families; the numeric GF180 sample agrees with ngspice on all 18 devices with 0 mismatches (raw deck exit 0 confirmed first); the symbolic template is "oracle unavailable" (<code>Undefined parameter [m_load_1_w]</code>) and its six <code>missing-model</code> diagnostics are genuine (<code>pch_lvt</code>/<code>nch_lvt</code> are not in the GF180 library); the IHP sweep's six OSDI <code>N</code> devices are recognised and its oracle is unavailable because ngspice has no PSP OSDI model loaded; the sky130 <code>tt</code> wrapper extracts cold in 5.5 s and warm in 2.1 s from the cache (171 files, 188 subckts, 1,019 models, 14,060 params) with a definition view of <code>sky130_fd_pr__nfet_01v8</code> through its defining file in 1.4 s. The first coverage run exposed four GF180 library constructs (sibling-section <code>.lib</code> references, <code>+</code> continuations across blank lines, <code>.ends othername</code>, diagnostics in unselected sections) and the OSDI letter; all fixed with fixtures and ngspice-verified rules. Strict suite green (<code>HX_REQUIRE_TOOLS=1 HX_REQUIRE_VENDOR_TOOLS=xyce,xdm</code>; the vendor variable existed before the Xyce checks did, as the registry and conftest marker shipped with N1). Not committed (user commits).</li>
<li><strong>2026-10-14</strong> — Phase N1.1 done (review fixes; the critique's six defects and two test gaps all reproduced, plan reviewed three rounds). Canonical nets through each occurrence's ancestor chain and immediate-binding wiring diffs; merged declaration records with ghosts listed; reference alternatives; switch grammar with an oracle that never skips a required model and filters both sides by subtree; guard-aware scope hashes; standalone library entries (deck role, omitted deck replayed as omitted); expression canonicaliser; definition-rooted oracle checks per instance. Strict suite green; coverage rerun <code>~/hx-review-artifacts/netlists/review-fixes-20261014/</code> unchanged (GF180 18/18, sky130 within thresholds). Not committed (user commits).</li>
<li><strong>2026-10-16</strong> — Current-state amendment: recorded first-<code>.github</code> root discovery, invocation-local graph lookup, stable per-entry current files, immutable history and provenance, and the tutorials/API reference site. Managed viewer/export graphs now use the same shared annotation path as MCP, including historical snapshots; standalone and explicit overrides retain their defaults. Initialization imports one unambiguous legacy sidecar atomically without replacing shared notes or altering the source; export only reads it. Migration preflights selection before graph commits and preserves the existing ID-mapping backups. Reserved annotation filenames are excluded from graph selection, history retention and dependency scanning. README/reference docs now distinguish supported CLI flags from planned netlist integrations, include <code>instance</code> edges, and explain strict/vendor test policy. CI installs and checks ngspice. Superseded schema/ID examples and closed browser/hide-UI items are labelled historical; original dated benchmark claims are retained. Validation: 366 tests passed with <code>HX_REQUIRE_TOOLS=1</code> and the virtualenv's executables on PATH, including browser workflows and the live ngspice oracle; strict MkDocs build passed; 27 README CLI examples parse and README/SSOT local file links resolve. Existing project graph/annotation files remained unchanged, and no <code>.hx</code> directories were created under the test cases.</li>
<li><strong>2026-10-16</strong> — Version 0.5.0: Rust/Xyce/circuit-review implementation. HSPICE and Spectre are deferred until their tools are available. Rust uses deterministic trait-aware hx/4 IDs, source-based migration with annotation backups, correct Unicode/token boundaries, canonical attribute-function selections/ranges, reasoned generated-target ghosts and caller-only fetching. Native Xyce uses a pinned 7.10 inventory and grammar; independent Xyce/XDM checks retain mirrored inputs and distinguish agreement, mismatches and unavailable coverage. Added saved-graph net/uses CLI and MCP queries, guarded net highlighting, definition/model navigation, and dedicated circuit changes with before/after declaration records in served and exported viewers. Small fixtures run in normal CI; the explicit acceptance runner uses the pinned Codex checkout, independent syn source audit and local Xyce/XDM manifest. Regression validation: 389 tests passed with <code>HX_REQUIRE_TOOLS=1</code> and <code>HX_REQUIRE_VENDOR_TOOLS=xyce,xdm</code>; all 5 Node tests and strict MkDocs passed. A freshly installed wheel passed packaged-data, Rust-helper, Xyce extraction, saved-net query and standalone-export smoke checks outside the source tree. Production acceptance: all 19 stages passed against pinned Codex <code>221e4e7c05386d06aa7b91da2a9b04f7f2bd921f</code> with Rust/rust-analyzer 1.95.0, Xyce 7.10.0-opensource and the XDM 2.7.0 bundle. All 48 extractions passed; all 24 forward/reverse comparisons matched, including unresolved identities and call sites. The independent syn audit checked 4,090 call-site ranges with zero argument mismatches or unexpected mapping gaps; 17 opaque macro sites retain explicit span evidence. Both sessions issued 2,767 requests; readiness was 42.59/42.00 s and extraction cases totalled 161.49/167.75 s. These are bounded views (maximum 200 nodes), not whole-workspace extraction. Xyce agreed on all five decks; XDM agreed on two and reported the three manifest-pinned coverage gaps as unavailable. Full reports, tool identities and the runtime source fingerprint are under <code>~/hx-review-artifacts/hierx-0.5/rust-acceptance/</code>. The Codex checkout remained clean and test fixtures contain no <code>.hx</code> directories. Not committed (user commits).</li>
<li><strong>2026-10-16</strong> — Review follow-ups 1.2 (whole-repo critique against this file, the README, the reference and tutorial docs and the test suite; the critique itself was reviewed three rounds and every overstated claim corrected before approval). Code: <code>hx hook install</code> reports an invalid or unwritable <code>settings.json</code> with exit 2 instead of a traceback; every <code>hx netlist check</code> report carries <code>scope</code> and <code>dialect</code> lines (xyce/xdm always check the whole deck and read <code>--dialect auto</code> as xyce; ngspice narrows to an instance subtree or compares a definition per unguarded instance); a simulator timeout or unexecutable binary is <code>oracle unavailable</code>, not an exception; an import-time guard names a missing <code>xyce_devices.json</code>; help strings for <code>track</code>, <code>migrate --keep-history</code> and <code>netlist check</code>; dead <code>diff._decl_hashes</code>, <code>spice_fe._elab_for</code>, <code>names.guard_exclusive</code> removed. Tests: <code>tests/test_netlist_oracle_fakes.py</code> drives every oracle failure branch with fake simulators (ngspice <code>net</code>/<code>name-form</code>/<code>missing-in-ngspice</code>/model-name/ref-count mismatches, rejection, garbage, timeout, instance and definition scopes; Xyce reject/family/net/topology/ timeout/no-deck/unexecutable; XDM agree/missing/extra/translation-loss/missing-U/empty), so CI covers <code>hx/netlist/xyce.py</code> without vendor tools; fixtures <code>fail/{malformed.sp,lib_errors.sp, sections.lib}</code> assert eleven parser structure diagnostics and the four <code>.lib</code> errors; <code>duplicate-definition</code>, <code>ambiguous-model</code>, <code>hierarchy-too-deep</code> (66-level chain), server 409/400/400 and a failed background extraction, MCP ambiguity/query errors/<code>search(kind)</code>/ <code>diff_since(ts)</code>/<code>save failed</code>, tool resolution order and the cache's missing-file sentinel (<code>tests/test_tools_cache.py</code>), <code>find_sources</code>, <code>cross_compiler_args</code>, <code>expr_text</code>/<code>port_text</code>, <code>_filename_time</code>, hook merge, <code>watch(run_first=False)</code>; the conformance truncation assertion can now fail; the circuit-diff browser test drives the <code>#diff-base</code> picker; ngspice is a required tool in the tutorial test too. Docs: tutorial query block fixed (<code>hx netlist net outa</code>) and executed by <code>test_tutorials.py</code>; C++ qualified entries documented as accepted (<code>src/main.cpp:hw::run</code>); CLI exit table, graph/diff field lists, README diagnostics (shadowing is a record status, not a diagnostic; six codes added), oracle, dialects, HTTP and MCP lists, tool fallbacks, Develop layout; the 0.5.0 section sits above License. Record: historical sections above are labelled rather than rewritten, the status log is in date order, "Where the 0.5.0 code lives" names every 0.5.0 module and test, the matrix's three wrong test names and the <code>.measure</code>/<code>.func</code> row are corrected, the failed <code>rust-acceptance-v2..v4</code> directories carry <code>SUPERSEDED.md</code>. Packaging: <code>dev/scripts/wheel_smoke.sh</code> builds the wheel, installs it into a fresh venv and runs extraction, queries and export from outside the checkout (passed locally: 10 data files + 4 vendored libraries, netlist, Xyce and Rust extractions); CI runs it after the clean base install; <code>coverage</code> joins the <code>dev</code> extra. Validation: 414 tests passed in 189 s with <code>HX_REQUIRE_TOOLS=1 HX_REQUIRE_VENDOR_TOOLS=xyce,xdm</code> (no skips); strict MkDocs build passed; coverage.py with subprocess measurement 91.8 % of 9,622 statements (lowest: <code>fsutil.py</code> 78 %, the no-<code>fcntl</code> fallback; <code>lsp_fe.py</code> 83 %; <code>clang_fe.py</code> 86 %). The 0.5.0 tree was committed by the user as <code>7e010e4</code> during this phase; the 1.2 changes were uncommitted at the time of that report (user commits). Historical attribution: these are the Phase 1.2 measurements, not a coverage run of 1.3 or the current baseline. The user subsequently committed 1.2 as <code>122584f</code> and 1.3 as <code>39202cf</code>; the 2026-10-18 baseline below records verification of that checkout.</li>
<li><strong>2026-10-16</strong> — Review follow-ups 1.3 (the two P2 findings the reviewer left open on 1.2; both were in committed code). Packaging: <code>dev/scripts/wheel_smoke.sh</code> ran its package-data check with <code>python -</code> from the caller's directory, so from the checkout root (locally and in the CI step) <code>import hx</code> resolved to the source tree, not the installed wheel; the check now runs from the (absolute) work directory with isolated Python (<code>-I</code>) and exits unless <code>hx.__file__</code> lies under the fresh venv, printing the imported path. Oracle: a device-rooted <code>hx netlist check</code> extracted a graph holding that device alone (plus the targets of its <code>ref</code> edges) while the listing was cut to the ENCLOSING instance, so every sibling was <code>missing-in-hx</code> (a deck-level device entry saw the whole listing); present since 7e010e4. Now <code>compare(..., subtree=P, device=NAME)</code> narrows BOTH sides to the one device (scope line <code>device x1.r1</code>; instance and definition entries unchanged); the selector comes from the entry's occurrence (<code>occ.path</code>), never from the display qualname, whose dots are escaped (<code>x1.r\.foo</code>; the instance branch shared that flaw); and a listing row spelled exactly as an in-scope hx device expects is in scope BEFORE the tolerant <code>strip_letters</code> decode, which cannot carry a bare-letter or dotted device name (ngspice 45.2 lists <code>r a b 4k</code> inside <code>x1</code> as <code>r.x1.r</code> and <code>r.foo</code> as <code>r.x1.r.foo</code>; the subtree filter used to drop such rows and report <code>missing-in-ngspice</code>). Tests: <code>test_netlist_oracle_fakes.py::test_fake_ngspice_device_entry_narrows_both_sides_to_that_device</code> (sibling, deck-level, <code>ref</code>-target <code>out_of_scope_hx</code>, <code>x1.r\.foo</code>, <code>x1.r</code>, instance and whole-deck counts) and <code>::test_fake_ngspice_wrong_net_on_odd_names_is_never_zero_comparison_agreement</code> (one <code>net</code> mismatch with one device compared, never zero-comparison agreement); <code>test_netlist_oracle.py::test_device_scope_keeps_exact_spellings_and_narrows_both_sides</code> (pure <code>compare</code>) and live assertions in <code>::test_live_agreement</code> (<code>ota.sp:xa.m_load_1</code>, <code>ota.sp:f1</code>, fixture <code>oracle/odd_names/odd_names.sp</code>). Docs: the README oracle bullet, the netlist tutorial and the dialect matrix's oracle row name the device scope.</li>
<li><strong>2026-10-18</strong> — Baseline review and Phase II direction. Reviewed implementation commit <code>39202cf</code> (clean tree): the strict suite passed <strong>417 tests in 154.64 s, no skips</strong>, with <code>HX_REQUIRE_TOOLS=1 HX_REQUIRE_VENDOR_TOOLS=xyce,xdm</code> and the virtualenv/Cargo executables on PATH; strict MkDocs passed. The Phase 1.2 414-test / 91.8% coverage result is retained under its original entry, without claiming a new coverage or production-acceptance run. Reorganized this SSOT around current capabilities, evidence boundaries, the planned architecture contract/composition/binding/evaluation flow, native build/test evidence, and review integration. The user selected expandable in-place history and native project tests for the initial compiled-test scope; generated executable contract tests remain deferred. Completed phase details, implementation map, original headings, and dated findings remain in this file. The new Phase II is distinct from the historical viewer/server Phase 2 and introduces no implemented API. Artifact retention: cleanup removed nine rebuildable target/environment directories, reclaiming <strong>52.97 GiB</strong>; <strong>3.68 GiB</strong> remained in the artifact root. All <strong>109,718</strong> retained file/symlink entries verified unchanged with no errors; small cache diagnostics were archived. The cleanup record is <code>~/hx-review-artifacts/cleanup-20261018T235532Z/manifest.json</code>, with <code>cache-diagnostics.tar.gz</code> beside it; passing production reports remain at <code>~/hx-review-artifacts/hierx-0.5/rust-acceptance/</code>. Future runs rebuild the caches. SSOT revision validation: strict MkDocs and all three documentation reference tests passed. A GFM preview in Chromium verified all ten expandable sections; all existing anchors except the intentionally updated status date, all seven local links and their fragments, all ten completed milestone bodies, and all 17 pre-existing dated entries were preserved or resolved. This documentation edit did not rerun the full suite, coverage, or production acceptance.</li>
<li><strong>2026-10-18</strong> — Typora folding correction. The preceding revision verified GFM rendering in Chromium, which did not verify Typora live preview. Typora splits HTML blocks at blank lines and leaves Markdown inside them unparsed. Converted the ten folded bodies to continuous HTML with rendered headings, lists, links, and code blocks; code newlines are represented as HTML entities to preserve their displayed whitespace without splitting the containing block. Historical content and heading identifiers are retained; folded sections are now edited as HTML. The current baseline and Phase II roadmap remain Markdown. Validation: all ten folded bodies opened and closed in the installed Typora 1.14.9 using a temporary document and isolated profile/display; browser comparison preserved historical text, heading identifiers, links, and code whitespace, and strict MkDocs passed. The existing editor session was left untouched and the isolated test editor was closed. No full-suite, coverage, or production-acceptance rerun was needed for this document-format correction.</li>
<li><strong>2026-10-21</strong> — Repository review and Phase II readiness amendment. Reviewed clean checkout <code>fa9e712</code>, whose changes since implementation baseline <code>39202cf</code> are documentation-only. Strict suite: <strong>417 passed in 195.67 s, no skips</strong>, with <code>HX_REQUIRE_TOOLS=1 HX_REQUIRE_VENDOR_TOOLS=xyce,xdm</code> and virtualenv/Cargo tools on PATH; all five Node viewer unit tests and strict MkDocs passed. All 22 explicit dialect-matrix test references resolved. Temporary-workspace probes reproduced a Rust callback omitted from both edges and unresolved records, missed Rust toolchain/Cargo configuration creation in default watching, malformed annotation JSON returning HTTP 500, graph deletion without a watcher event, and incorrect splitting of a drive-qualified entry without a symbol. Non-object annotation PUT clears notes as explicitly documented; stricter validation is recorded as a compatibility proposal. Added the R1–R7 register with evidence, priorities, status, remedies, and acceptance criteria; corrected the unconditional unresolved-call claim and ngspice contributor policy. The user selected a readiness gate: contract design may proceed, while conformance acceptance requires R1–R4 checks. Expanded the roadmap with project/configuration-scoped identity, coverage-aware verdicts, and native-test selection, timeout, and freshness cases. This amendment changes documentation only; implementation findings remain open. Historical reports and dated text are retained; coverage, installed-wheel smoke, and production acceptance were not rerun. Amendment validation: strict MkDocs and seven documentation/reference and simulator-free tutorial tests passed (six toolchain/oracle tests deselected); all local links/fragments and previous heading anchors resolved. Nine folds and every historical status entry were preserved byte-for-byte; all ten folds remain continuous HTML. The updated status-log fold opened and closed in installed Typora using a temporary document and isolated profile/display.</li>
<li><strong>2026-10-21</strong> — Phase II.0 readiness foundation implemented in the working tree, pending a user commit. R2–R5 have code and regression coverage: shared Rust configuration candidates cover ancestors, Cargo home, legacy spellings and missing files, are captured before LSP startup, and remain watched with restricted source paths and before a first successful extraction; malformed annotation JSON returns 400 without writes/revisions/events; drive-qualified entries require a symbol separator; server creation/deletion events drive an unavailable viewer state that preserves graph identity and queued notes, recovers on recreation, and rejects stale graph/source/history/diff responses. Annotation refresh also tolerates server revision resets. R1 adds sorted optional <code>meta.evidence_limits</code> with <code>entry-view-only</code> and LSP <code>lsp-call-omissions</code>; empty/absent limits do not establish completeness. hx/4, hx-ann/1, symbol IDs and documented non-object annotation PUT normalization remain compatible. Final strict suite: <strong>451 passed in 169.92 s, no skips</strong>, with <code>HX_REQUIRE_TOOLS=1 HX_REQUIRE_VENDOR_TOOLS=xyce,xdm</code> and virtualenv/Cargo tools on PATH. All five Node tests and strict MkDocs passed. The installed-wheel smoke passed from an unrelated directory with package-data checks and netlist, Xyce and Rust extractions. One preliminary run had 449 passes and one failure in the new rapid-edit watch test because the edit could retain its timestamp; the test now sets a distinct timestamp explicitly. Coverage and the full production Codex corpus were not rerun. All ten SSOT folds retain continuous HTML; nine historical folds, all 20 HEAD status entries and the preceding review amendment are preserved, 34 previous heading anchors remain, and all 24 local links/fragments resolve. The updated status-log fold opened and closed in installed Typora using a temporary document and isolated profile/display. Verification logs and small reports are in <code>~/hx-review-artifacts/hierx-0.5/readiness-20261021-PRGGPo/</code>. R1 evaluator safeguards remain open for II.2; R6 remains a separate compatibility proposal. The next implementation stage is II.1 intent/composition/bindings on a controlled Rust fixture, with native compiled-test evidence in II.3.</li>
<li><strong>2026-10-21</strong> — Phase II.1 intent/composition/bindings implemented in the working tree, pending a user commit. The preceding readiness foundation is now committed as <code>1302535</code>; R2–R5 are closed with its recorded 451-test acceptance, while R1 evaluator safeguards remain open for II.2 and R6 remains a compatibility proposal. Added reusable local <code>hx-contract/1</code> TOML, separate <code>hx-bindings/1</code> TOML, the <code>hx.contracts</code> Python API, <code>hx contract validate/project</code>, and versioned <code>hx-projection/1</code> reports. Composition validates qualified instances, port types, child wiring/exposure/delegation, cycles and duplicates. Scoped bindings enforce direct ownership and parent aggregation. Projection reconciles shared known build/source observations without requiring equal whole-view option/input hashes; conflicting or unsettled evidence is quarantined, unknown provenance stays explicit, and relationships retain source witnesses. Authored inputs, graphs and annotations remain read-only; output requires a new derived file. No architectural verdict, native-test evidence ingestion, MCP or viewer integration is added. A safe Rust fixture reuses two cache contracts, passes three Cargo tests, and projects both application → service → storage and a deliberate application → storage bypass. Final strict suite: <strong>508 passed in 178.59 s, no skips</strong>, with <code>HX_REQUIRE_TOOLS=1 HX_REQUIRE_VENDOR_TOOLS=xyce,xdm</code>. All five Node tests, strict MkDocs and installed-wheel smoke passed, including 13 package-data files, four vendored libraries, the new schemas and both contract commands outside the checkout. Regression coverage includes malformed inputs, composition, empty/overlapping/foreign bindings, scoped identity, conflicting revisions/build settings/symbols, unknown or incomplete evidence, immutable inputs, equivalent-order semantics, legacy Rust migration, and live overlapping entry views. Exact-byte input hashes intentionally change when input bytes change. SSOT history and heading anchors are preserved; all ten folds remain continuous HTML. Small reports and logs are retained at <code>~/hx-review-artifacts/hierx-0.5/contracts-20261021-xet9w4vz/</code>; temporary build environments are rebuildable. Coverage and full Codex production acceptance were not rerun. Next: II.2 structural conformance with explicit coverage-aware results; II.3 native-test evidence binding follows.</li>
<li><strong>2026-10-22</strong> — D2 boundary-port feasibility experiment implemented privately under <code>dev/d2_ports_experiment/</code>. Revised direction: retain a small Hx model of blocks, named input/output ports, and connections while investigating D2 authoring/presentation; defer further contractual meaning, type/required-connection checks, behavioral obligations, native-test evidence ingestion, and testcase generation. Existing TOML commands and projection behavior remain in place. Official unmodified D2 v0.9.0, verified against the release asset digest, supplies all geometry; Hx only measures SVG and supplies navigation metadata. ELK/default, Dagre/default, TALA/default, and ELK/zero-padding each compile flat, nested imported/reused-child, and editing-stress cases. All <strong>12 renders / 24 zoom views fail</strong> the visible boundary-pin gate; no profile qualifies. Pin centres remain inside containers, including a minimum five-unit distance for zero-padding ELK against the two-unit tolerance. Native link icons obscure all pin centres; <strong>62 of 64 block-title clicks</strong> reach the expected Hx function/signature/source, with Dagre nested-label overlap obstructing the other two. Some nested/stress cases also fail endpoint or label checks. Three native table-row controls compile but cannot qualify as visible pins. No layout repairs, fallback renderer, production D2 API/dependency, or TOML migration is added. Result exit 1 records a completed negative experiment, with zero unresolved bindings or measurement errors; passing profiles alone would trigger two further stability runs. Verification: <strong>72 focused tests passed in 9.81 s</strong> (13 private oracle/browser, 56 existing contracts, three documentation-reference tests), strict MkDocs passed, and the separate Rust fixture passed two Cargo tests. Mutation tests reject displaced/missing pins, wrong endpoints, missing exposure, overlapped labels, broken targets, unmeasurable markers, and a cancelled actual browser click. Reports, original SVGs, measurements, screenshots, native-test logs, versions and hashes are retained at <code>~/hx-review-artifacts/hierx-0.5/d2-ports-20261022-l9_xc0uu/</code>; disposable tools/builds are removed. Decision: keep TOML, reconsider D2's role or another presentation approach before a separately scoped integration experiment, and retain II.2–II.4 as deferred designs. This result does not prove every possible D2 encoding fails. All ten SSOT folds retain continuous HTML; nine historical folds, previous dated entries, heading anchors and local links are preserved or resolve. The final status fold was opened and closed in isolated Typora. No new full-suite, installed-wheel, coverage, or production Codex acceptance measurement is claimed.</li>
<li><strong>2026-10-23</strong> — Architecture contract interface direction documented in <a href="architecture-contract-interface.md">architecture-contract-interface.md</a> beside this SSOT. Retain TOML authoring and add an explicit design for named inputs/outputs whose arrows represent data or signal flow. The note distinguishes existing <code>provides</code>/<code>requires</code> service connections from proposed dataflow ports, illustrates producer/consumer composition with structured <code>from</code>/<code>to</code> connections, and retains quoted arrow strings as optional future shorthand. Boundary pins, readable wire labels, nested exposures, reused instance identities, and code navigation remain presentation requirements; renderer selection is separate. Proposed examples are not accepted <code>hx-contract/1</code> syntax. Existing service contracts and validation retain their meaning; further semantic checks and testcase generation remain deferred. Updated the current direction and roadmap links while retaining D2 findings and historical verification dates. This documentation change adds no parser, schema, CLI, or viewer behavior. Strict MkDocs passed; all five TOML fragments parse, the current connection matches the fixture, and the proposed endpoint and shorthand examples agree. Small documentation and editor-verification reports are retained at <code>~/hx-review-artifacts/hierx-0.5/contract-interface-20261023-783itglu/</code>.</li>
<li><strong>2026-10-23</strong> — Hx/D2 interpretation and direct ELK experiment direction recorded in this SSOT and the <a href="architecture-contract-interface.md#next-experiment-hxd2-interpretation-and-direct-elk-layout">interface design note</a>. First reuse existing D2 syntax/parsing with Hx architecture interpretation rather than maintaining a D2 compiler fork, then test direct ELK layout and Hx presentation. This explicitly relaxes the earlier stock-D2-only geometry constraint. Four required demonstrations are a width-labelled wide signal, expandable bundle, forward data/valid with reverse ready, and nested child-bundle exposure, all with boundary pins and working code links. Retain the two-unit geometry, zoom, edit-stress, and repeat-stability gates. Upstream ELK capabilities motivate the candidate; no direct-ELK feasibility result is claimed. The completed stock-D2 section, original failures/artifacts, and prior dated entries remain unchanged. Implemented TOML contracts/commands remain available, the earlier TOML dataflow examples remain a reference, and type compatibility, behavioral validation, and testcase generation stay deferred. This amendment changes repository documentation only; it adds no parser, renderer, schema migration, or public API. Strict MkDocs and local link/anchor/example checks passed. Small reports and editor-verification evidence are retained at <code>~/hx-review-artifacts/hierx-0.5/d2-elk-direction-20261023-cvg91jmt/</code>.</li>
<li><strong>2026-10-23</strong> — D2 syntax accepted for new Hx architecture sketches, with upstream parsing and an Hx interpretation layer rather than a compiler fork. Updated this SSOT and the <a href="architecture-contract-interface.md">interface design</a> to distinguish the accepted authoring decision from unimplemented parser integration and unverified direct ELK rendering. Immediate scope is blocks, individually named input/output boundary ports, explicit wires, nested individual-port exposures, and code navigation. Bus/bundle definitions, wide ports/signals, width/vector/lane handling, bundle expansion, mixed-direction bundles, and complete child-bundle exposures move to the <a href="architecture-contract-interface.md#future-plan-buses-and-wide-ports">future plan</a>; the reduced ordinary-port scope supersedes the preceding four-case proposal for immediate acceptance. Independent scalar connections may still run in opposite directions. The earlier bus/width demonstrations remain future acceptance requirements. Implemented TOML contracts/commands, historical examples, stock-D2 results, and prior dated entries remain intact. This decision changes documentation only; it adds no parser, renderer, public API, or automatic migration. Further semantic validation and testcase generation remain deferred. Strict MkDocs passed; documentation and editor checks are recorded at <code>~/hx-review-artifacts/hierx-0.5/d2-syntax-decision-20261023-dkchdgaf/</code>.</li>
<li><strong>2026-10-23</strong> — Retired the uncommitted Phase II.1 TOML contract feature after verifying a reference archive containing source, schemas, fixtures, tests, integration files, and all original acceptance reports. The <a href="retired-toml-contracts.md">retirement index</a> records its checksum, manifest, baseline commit, and separate-checkout restoration instructions. Removed the loader/projection API, <code>hx contract</code> commands, three schemas, 25 feature files, and associated public docs, example preparation, and positive packaging checks. Preserved projection unchanged in the archive, without extracting a generic backend. Committed extraction/provenance/evidence-limit/viewer foundations and D2 experiment files remain unchanged; shared graph-reader edits are documentation-only, and TOML project configuration remains supported. All 26 prior dated entries and stock-D2 results are retained. Verification: <strong>451 remaining strict tests passed in 170.41 s, no skips</strong>, with required tools and Xyce/XDM; 57 feature-specific tests were archived/removed. All <strong>13 private D2 oracle/browser tests passed in 9.14 s</strong>, and strict MkDocs passed. A clean installed wheel passed outside-checkout netlist/Xyce/Rust smoke, contained ten data files and four vendored libraries, omitted the retired package/schemas, and rejected the old command with usage exit 2. Small current reports are retained beside the archive at <code>~/hx-review-artifacts/hierx-0.5/toml-contracts-retired-20261023T232122Z/</code>. Original acceptance reports remain byte-identical; coverage and production Codex acceptance were not rerun. D2 syntax remains selected, its interpretation/rendering remains unimplemented, and buses/wide ports remain deferred. Changes are uncommitted.</li>
<li><strong>2026-10-23</strong> — Implemented Phase II.1b D2 architecture authoring after the separate direct-ELK gate passed: 24 case/zoom/repeat combinations and 288 genuine code clicks cover ordinary boundary ports, explicit wires/exposures, nested imported reuse, stress/fan-out and reverse-flow scalar connections. Added the optional pinned upstream compiler bridge, separate <code>hx-arch/1</code> data/schema, dedicated <code>hx arch inspect/serve/export</code>, offline diagram assets and exact navigation links into the existing source viewer. Parser, interpretation, navigation, layout and presentation remain internal extension seams; no bus/width syntax or contractual verdicts are added. All 27 prior dated entries, stock-D2 files/results, extraction/viewer foundations and the retired TOML archive are preserved. Verification: <strong>488 strict tests passed in 185.84 s, no skips</strong>; 37 final architecture checks, 13 original private D2 tests, five Node tests, Go tests, strict MkDocs and clean installed-wheel netlist/Xyce/Rust/D2 smoke passed. Source ranges and optimized-Python protocol checks are covered. Reports, original SVGs, screenshots, input/tool hashes and findings are retained at <code>~/hx-review-artifacts/hierx-0.5/d2-integration-20261024T001707Z/</code>. Buses, bundles, conformance/test evidence and testcase generation remain deferred. Coverage and production Codex acceptance were not rerun. Changes are uncommitted.</li>
<li><strong>2026-10-23</strong> — Corrected D2 bridge setup to handle its Go prerequisite. Explicit setup now reuses Go 1.27+ or downloads SHA-256-verified Go 1.27.3 into a persistent user-local SDK directory, then atomically installs the version-checked bridge. Added <code>--go-dir</code> and <code>--no-bootstrap</code>; system Go and shell profiles are unchanged, and runtime commands still never fetch tools. Documented why the thin Go adapter calls the upstream compiler while Hx interpretation remains Python and presentation remains JavaScript. Verification: <strong>51 focused tests passed, no skips</strong>, including 18 installer cases; actual missing-Go installation/build, cached-SDK reuse, Go tests, architecture smoke and strict MkDocs passed. The rebuilt helper is byte-identical to the previously verified binary. All 28 prior dated entries and original D2/TOML evidence are retained. Small reports are at <code>~/hx-review-artifacts/hierx-0.5/d2-go-bootstrap-20261024T010316Z/</code>. The full suite, wheel and presentation matrix were not rerun for this setup-only amendment. Changes are uncommitted.</li>
<li><strong>2026-10-23</strong> — Added five runnable repository-based D2 sketches under <code>tests/d2_bridge/</code>: Codex path resolution and asynchronous search, FFmpeg transcoding and reused audio/video paths, and Hx extraction/persistence/review. Bundled 15 pinned source files and seven license/notice files (635,882 bytes), plus 35 genuine declaration records for a locally rebased navigation-only catalog. Every block and port has an explicit source target; authored arrows do not become extracted call edges. The local wrapper/README cover setup with Go bootstrap, inspection, one-process gallery/individual previews, editing, offline/live-link export, browser checks and cleanup. Generated HTML, screenshots and geometry remain ignored; compact findings are retained beside the examples. Verification: <strong>529 strict tests passed in 197.34 s, no skips</strong>, including the 23 new regression checks; <strong>60 measured views and 684 genuine source clicks passed</strong> across three layouts and 100%/150% zoom, retaining the existing two-unit tolerance. Cached-SDK bridge setup and strict MkDocs also passed. Relocation, negative source/binding/topology checks, local annotation/history placement, foreground server lifecycle, multilingual source text and offline/live exports are covered. Final fitted-view captures caught a label touching its pin under font hinting; the native ELK adapter now requests eight units of horizontal label/port spacing, and both fitted and actual-scale views are measured without relaxing tolerances. Wide fit views require zoom/pan. These bounded authored views do not qualify whole-repository architectures or contractual meaning; buses/bundles remain deferred. Prior dated entries, stock-D2 evidence, earlier Hx/ELK acceptance and the retired TOML archive are preserved. Changes are uncommitted.</li>
</ul>
</details>
