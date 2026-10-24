# Hx/D2 interpretation and direct ELK acceptance

This is the separate Phase II.1b experiment. The original
[stock-D2 experiment](../d2_ports_experiment/README.md) and its negative result
remain unchanged. Here upstream D2 owns parsing/import expansion, Hx interprets
ordinary blocks/ports, and ELK supplies native-port compound layout for the Hx
SVG presenter. This tests authored presentation/navigation, not conformance.

Build the bridge, then run from the checkout with Playwright/Chromium and Rust
tools installed:

```bash
bash dev/scripts/setup_d2_bridge.sh
.venv/bin/python dev/d2_integration_experiment/run.py \
  --bridge "$HOME/.cache/hx/tools/bin/hx-d2-bridge" \
  --elk hx/viewer/vendor/elk.bundled.js \
  --output /tmp/hx-d2-elk-acceptance
```

The output directory must not exist. `--case` can select flat, nested, stress,
or handshake cases. The first three retain the independent original fixture
expectations; handshake adds a separately authored forward-data/reverse-ready
case. Expected topology is not generated from interpreted output. The SVG
measurement adapter reads browser primitives, text boxes and actual routes;
the original independent geometry checker measures boundary/endpoint errors,
labels and unrelated-block crossings. Genuine title/pin clicks must reach the
expected Hx source and signature. No clicks are forced through obstructions.

Every case runs three compilations at both 100% and 150% CSS zoom. It must pass
the two-SVG-unit pin/endpoint tolerances, missing-measurement checks, readable
labels, code clicks and identity/topology expectations every time. The runner
keeps inputs, model/layout output, original SVGs, measurements, screenshots and
click outcomes. The Rust fixture's two Cargo tests keep it executable; they do
not discharge architectural obligations. Temporary Cargo targets are removed.

The initial run passed 18 combinations for flat/nested/stress and a separate
handshake run passed six. Evidence is at
`~/hx-review-artifacts/hierx-0.5/d2-integration-20261024T001707Z/`.
Only after these gates passed were public commands and vendored ELK promoted.
Regression tests mutate rendered pins/routes/labels/targets/markers and cancel
a real click to prevent a false pass. Small evidence is retained; duplicate
HTML bundles and disposable build caches can be regenerated and removed.

Future bus/width/bundle cases remain deferred. The internal parser, interpreter,
model, binding, layout and presentation boundaries are extension points; no new
D2 grammar or reserved bus syntax is introduced.
