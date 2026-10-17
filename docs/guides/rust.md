# Rust

Install the Rustup `rust-analyzer` and `rust-src` components described in
[installation](../getting-started/install.md). Ensure `cargo`, `rustc`, and
`rust-analyzer` are on PATH. Prepare the fixture from the checkout:

```bash
python examples/prepare.py rust /tmp/hx-rust-tutorial
cd /tmp/hx-rust-tutorial
```

<!-- hx:test rust-extract -->
```bash
hx extract src/lib.rs:app_run --depth 2 --lsp-timeout 120
```

The root contains `Cargo.toml`; rust-analyzer uses it to discover the project.
The summary reports the server and readiness time. View the result with
`hx serve --open` and inspect `dma_start` and its parameters.

For your own project, use the Cargo package/workspace root and a file defining
the requested function. Increase `--lsp-timeout` for a large workspace. Override
the executable with `--lsp-cmd 'rust-analyzer'` when needed.

Nodes have `precision: lsp`. Signatures and call edges come from the language
server. Struct fields do not include memory sizes or offsets; globals are not
extracted. Indirect calls and closures may be absent. hx starts a language server
for each extraction, so repeated runs still incur startup and indexing time.
Use [tracking](../reference/configuration.md) to retain extraction options.

Qualified entries retain their full Rust spelling. For trait implementations use
`'src/lib.rs:<Item as Convert<String>>::convert'`; ambiguous bare methods list
candidates. IDs include trait arguments and remain stable when comments or line
positions change. Rust parsing preserves closure arguments, nested comments,
raw strings, lifetimes and turbofish syntax. Index metadata includes request
counts by method and timing; indexing timeouts fail explicitly.
Targets reported at macro invocation locations without a matching function
declaration remain explicit unresolved records. hx does not invent positional
IDs for them.
Attribute-decorated functions use the declaration's name and range for hover
and hashing. Hover documentation examples cannot supply another function's
signature; a missing signature falls back to the source declaration header.

The production acceptance corpus is the OpenAI Codex workspace pinned to
`221e4e7c05386d06aa7b91da2a9b04f7f2bd921f`. Install
its Rust 1.95.0 toolchain with rust-analyzer/rust-src, prepare a clean checkout
at the revision in the runner, then run from hierX:

```bash
python dev/scripts/hardening_coverage.py --suite rust --codex-root /path/to/codex --out /tmp/hx-rust-coverage
```

The runner analyzes eight entry points with depth/caller variants in two fresh
server sessions, reverses discovery order, and audits argument boundaries with
a development-only `syn` helper. JSON/Markdown reports retain tool versions,
the hx source fingerprint, timings and source-mapping gaps. A gap is accepted
only when the independent parser places it inside an opaque macro body; other
unmapped sites and argument mismatches fail the run. These are bounded views,
not an exhaustive Codex call graph. Normal CI uses the small Rust fixtures and
does not download or analyze Codex.
