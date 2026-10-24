# Retired TOML contract reference

**Retired: 2026-10-23.** The experimental Phase II.1 TOML contract feature has
been withdrawn from the active package. At retirement, D2 syntax was selected
while its Hx interpretation and direct ELK presentation were unimplemented.
For subsequent ordinary-port implementation and acceptance, see the [interface design](architecture-contract-interface.md)
and [current SSOT](single-source-of-truth.md).

The retired `hx.contracts` API, `hx contract validate/project` commands, three
schemas, contract fixture, tests, and public tutorial/reference pages are retained
in the external reference snapshot below. They are no longer installed or tested
as active features. Normal project configuration still uses TOML.

## Snapshot

- Archive ID: `toml-contracts-retired-20261023T232122Z`
- Directory: `~/hx-review-artifacts/hierx-0.5/toml-contracts-retired-20261023T232122Z/`
- File: `reference.tar.gz` (504,550 bytes)
- SHA-256: `b69a90cba2cadb74578e627e3da4bdbf418e64d23aef5c3e0a4328d1b83b74b5`
- Baseline commit: `130253503b418d3aa900bfec1689d4cfac03afb8`
- State: uncommitted prototype over that baseline; captured before removal.

`manifest.json` records the original path, size, mode, and SHA-256 of every
archive entry. All 62 entries were read back and verified before source removal.
`reference.sha256`, `archive-verification.json`, and `RESTORE.md` sit beside the
archive. The archive is intentionally external to Git; another checkout needs a
copy of these artifacts from their owner. The checksum identifies the snapshot
independently of its storage location.

## Archived source

`source/` contains 36 repository-relative files: 25 retired files plus supporting
integration files and package metadata needed to reconstruct the feature:

- `hx/contracts/{__init__,loader,model,projection}.py`.
- `hx/schema/hx-contract-1.schema.json`, `hx-bindings-1.schema.json`, and
  `hx-projection-1.schema.json`.
- The complete `tests/fixtures/contracts/rust/` source, contract/bindings TOML,
  Cargo manifest, and lockfile.
- `tests/test_contracts.py` and `tests/test_contracts_live.py`.
- `docs/reference/contracts.md` and `docs/tutorials/contracts.md`.
- The CLI, example preparer, wheel-smoke integration, README, documentation
  references/navigation, graph-reader documentation, and `pyproject.toml`.

Projection is preserved unchanged, including its dependence on the TOML loader
and service-interface model. Its evidence reconciliation, quarantine, scoped
identity, and source-witness logic are reference ideas for future D2 bindings;
there is no extracted generic projection backend in the active package.

## Historical acceptance

`acceptance/contracts-20261021-xet9w4vz/` contains all 21 original report files
unchanged, including the baseline/bypass/wheel projections, source hashes,
working-tree patch, strict-test logs, wheel logs, and verification metadata.
The original artifact directory is also preserved in place.

Those reports record **508 tests passing without skips**, five Node tests,
strict MkDocs, the installed-wheel smoke, and three Cargo tests. They describe
the 2026-10-21 implementation run, not current capabilities or a new reproduction.
All 36 historical source hashes were checked at retirement; only the subsequently
edited SSOT differed. Coverage and full production Codex acceptance were not
remeasured for that phase.

`context/` contains the pre-retirement SSOT/interface note, Git status, tracked
diff, and hashes of all nonignored workspace files. It is inspection material;
its patch includes later design decisions and is not a restoration overlay.

## Restore in a separate checkout

From this repository, verify the archive and restore only `source/` over a new
detached checkout of the baseline:

```bash
reference_archive="$HOME/hx-review-artifacts/hierx-0.5/toml-contracts-retired-20261023T232122Z"
(
  cd "$reference_archive"
  sha256sum --check reference.sha256
)
reference_checkout=$(mktemp -d /tmp/hx-toml-reference.XXXXXXXX)
reference_extract=$(mktemp -d /tmp/hx-toml-extract.XXXXXXXX)
git worktree add --detach "$reference_checkout" 130253503b418d3aa900bfec1689d4cfac03afb8
tar -xzf "$reference_archive/reference.tar.gz" -C "$reference_extract"
cp -a "$reference_extract/source/." "$reference_checkout/"
```

Use the snapshot's `manifest.json` to verify extracted files and modes. Install
the development, browser, and documentation extras and the original external
toolchains in that separate checkout before reproducing its tests. Consult the
archived verification metadata for exact commands and versions. Keep the active
checkout and its D2 work separate from this historical reproduction.

## Retirement verification

Current retirement checks are recorded separately in `retirement-verification.json`
and the new logs beside the archive. The original acceptance files remain
unchanged. The remaining strict suite passed **451 tests without skips**; the
**13 private D2 oracle/browser tests** and strict MkDocs also passed. A clean
installed wheel passed netlist/Xyce/Rust smoke checks and contained no retired
contract package or schemas; the removed command returned the normal usage exit 2.
The 57 archived contract tests are no longer part of the active suite.

Disposable verification builds/environments are removed after their small reports
are retained. Coverage and full production Codex acceptance were not rerun.
