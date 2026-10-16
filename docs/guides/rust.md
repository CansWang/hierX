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
