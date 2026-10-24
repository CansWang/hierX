# D2 boundary-port experiment

This private experiment tests whether unmodified **D2 v0.9.0** can present a
small Hx model of blocks, named input/output ports, and connections. Boundary
pins are an acceptance requirement. The experiment does not replace the TOML
implementation or add a production API, dependency, renderer, or contract check.

The 2026-10-22 run **did not qualify any profile**. ELK, Dagre, and TALA placed
the circle objects inside their containers. ELK with zero horizontal padding
also failed the two-unit boundary tolerance. Native link icons obscured the pin
centres. Some nested and stress layouts additionally failed endpoint or label
checks. Block-title links generally reached Hx source successfully.

Keep the existing TOML implementation while reconsidering D2's role. This result
applies to these encodings, version, and profiles; it is not a proof that every
possible D2 encoding fails. A separate experiment with another representation or
a port-aware renderer needs an explicit scope decision. No fallback renderer is
implemented here. Contractual meaning, type compatibility, required connections,
behavioral obligations, and testcase generation remain deferred.

## Reproduce

Use the repository's development environment with its existing Playwright extra
and Chromium, plus Cargo, rustc, and rust-analyzer. The runner temporarily puts
`~/.cargo/bin` first in its own process, records the actual tool versions, and
builds the Rust fixture in a disposable target directory. It changes no shell
configuration or system tool installation. The fixture lockfile uses version 3.

Obtain the official Linux x86-64 release privately; no global install is needed:

```bash
work=$(mktemp -d /tmp/hx-d2-tool.XXXXXXXX)
curl --fail --location https://github.com/d2lang/d2/releases/download/v0.9.0/d2-v0.9.0-linux-amd64.tar.gz --output "$work/d2.tar.gz"
printf '%s  %s\n' 5669ddc46b99e942cc96078f4a4e36d5e62103348f4c05179ede27802fdd87a9 "$work/d2.tar.gz" | sha256sum --check
tar -xzf "$work/d2.tar.gz" -C "$work"
.venv/bin/python dev/d2_ports_experiment/run.py \
  --d2 "$work/d2-v0.9.0/bin/d2" \
  --output /tmp/hx-d2-evidence
```

The output directory must be new or empty. The archive digest was checked against
the official GitHub release asset digest. The runner enforces the exact version,
records the binary hash, and requires all three engines to be present. Other
platforms need their corresponding official v0.9.0 asset and digest.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | At least one engine/profile qualified on every case, both zooms, and repeats. |
| 1 | Experiment completed; no profile qualified. This is the recorded result. |
| 2 | Setup or instrumentation failed; inspect `setup-error.json` and its traceback. |

The private oracle tests run explicitly, outside the normal production suite:

```bash
.venv/bin/python -m pytest -q dev/d2_ports_experiment/test_experiment.py
```

## Cases and independent checks

| Case | What it exercises |
| --- | --- |
| `flat.d2` | Two blocks, two named inputs and two outputs each, two labelled connections, differing input declaration order. |
| `nested.d2` | A parent with four exposed ports; two instances of imported `worker.d2`; four parent/child exposure wires and two child/child wires. |
| `stress.d2` | Longer block/port names, changed order, added input/output, and an extra fan-out connection to an observer. |
| `rows-control.d2` | Native SQL-table row anchors, rendered for comparison only. Rows do not qualify as separate visible boundary pins. |

Profiles are ELK/default, Dagre/default, TALA/default, and
ELK/zero-padding (`--elk-padding '[top=28,left=0,bottom=28,right=0]'`).
All use the same authored inputs, theme 0, and outer padding 30.

`model.py` contains the independent expected blocks, ports, connections, exposures,
and code bindings. D2 remains the authoring source; this fixture oracle is neither
a second user format nor a general D2 source parser. The shared worker instances
have different qualified diagram identities and deliberately share code symbols.
The runner only substitutes temporary code-link values in copied inputs.

`measure.js` reads the compiled SVG with Chromium. It decodes D2's documented
object identity classes, measures primitives and text in SVG coordinates, samples
routes, and accounts for the visible triangle arrow tip. Unknown primitives or
markers yield explicit measurement failures. `geometry.py` requires:

- Every expected block and port identity, and the expected connection endpoints,
  kind, and label; missing exposures cannot pass.
- A dedicated circle/ellipse/square no larger than 16 SVG units, with its centre
  within **2 SVG units** of its owning block's left input or right output border.
- Each wire's visible start/end within 2 units of its declared pin outline.
- Readable labels within the SVG view box, without label/label or label/pin
  overlaps, and no sampled route through an unrelated block interior.
- Exact resolved code-link targets and successful browser navigation.

The numerical comparison allows a `1e-6` rounding epsilon at the two-unit
threshold. Route sampling is every approximately two SVG units, capped at 10,000
samples; it is a practical overlap check, not an analytical intersection proof.

Checks run at **100% and 150% CSS zoom** in the browser. A qualifying profile must
then pass two more independent compilations with the same identities/topology;
pixel-identical layouts are not required. Failed profiles are not repeated.

No port is repositioned and no route is repaired. Inspection only adds locator
identity attributes and link `target` metadata. Genuine Playwright clicks on
block titles and pin glyphs must select the expected function in the existing Hx
viewer and display its source and signature. A covered centre is reported as an
obstruction; clicks are never forced through it. Port bindings name parameters or
tuple-return positions. Links navigate to their owning function; exact parameter
or tuple-token highlighting is not implemented or claimed.

The Rust fixture has two native Cargo tests. They demonstrate a safe example and
support source navigation; the results do not discharge architectural obligations.
No dataflow is inferred from its parameters or return tuple.

Oracle tests use an independently authored known-good SVG, then displace a pin,
attach a wire to a wrong endpoint, overlap a label, remove a pin/exposure, corrupt
a code link, and introduce an unmeasurable marker. A browser test verifies actual
title/pin clicks against the real Hx server and rejects a cancelled click even
when its href is correct. Missing tools and existing nonempty outputs are setup
failures, rather than passing or overwriting evidence.

## Evidence and inspection

The recorded run lives at
`~/hx-review-artifacts/hierx-0.5/d2-ports-20261022-l9_xc0uu/run/`.
Start with `findings.md` or `gallery.html`, then inspect:

- `report.json`: profile/case matrix, per-zoom checks and click outcomes, exact
  compiler commands, tool/harness/input hashes, versions, and recommendation.
- `renders/`: original SVGs, compiler logs, measured geometry, checks, and bounded
  viewport screenshots at both zoom levels. The SVGs retain the full drawings.
- `controls/`: SQL-table row comparison SVGs and logs, excluded from qualification.
- `model.json`, `inputs/`, `source/rust/`, `graph.json`: expected identities,
  compiled inputs, small Rust source snapshot, and the actual extracted graph.
- Version logs, native Rust test log, and engine help/inventory.

Serve the output directory with `python -m http.server --directory PATH`, then
open `gallery.html`. It embeds SVG as `<object>` so links remain interactive.
The experiment shuts down both local servers. To re-enable code links, use the
`reopen_code_links_command` in `report.json` from an environment containing Hx;
it starts the existing source viewer on the recorded loopback port. Keep the
evidence directory in place or adjust paths explicitly. A moved report does not
silently rewrite its original SVG links.

Keep small evidence; discard the private D2 archive/binary and temporary build
directories after use. The runner removes its Rust target/cache directories on
completion or failure. No tool binaries or generated evidence belong in Git.

## Upstream references

- [Pinned D2 release](https://github.com/d2lang/d2/releases/tag/v0.9.0).
- [SVG identity and embedding behavior](https://d2lang.com/tour/exports/).
- [SQL table row anchors](https://d2lang.com/tour/sql-tables/).
- [D2 FAQ on ports and SVG interactivity](https://d2lang.com/tour/faq/).
- [Upstream port discussion](https://github.com/d2lang/d2/discussions/605).

The documentation describes row anchors and currently reports no explicit port
facility. The acceptance decision here rests on the recorded compiler/browser
measurements, rather than treating that documentation as a substitute for a run.
