# Python source extraction

This page describes extracting Python application structure. For calling hx from
Python, use the [scripting tutorial](../tutorials/python-api.md).

Pyright and its packaged Node.js runtime are included in hx's base install.
Prepare the example from the checkout:

```bash
python examples/prepare.py python /tmp/hx-python-tutorial
cd /tmp/hx-python-tutorial
```

<!-- hx:test python-extract -->
```bash
hx extract hxfix/main.py:app_run --depth 2 --lsp-timeout 120
```

The copied `pyrightconfig.json` selects the fixture package. The resulting graph
shows server-provided calls and annotated dataclass fields. Open it with
`hx serve --open` and inspect the `DmaChan` type.

For your own project, use its repository root so imports and Pyright configuration
resolve correctly. Use qualified names for nested functions and methods, such as
`module.py:outer.helper`. Add `--include-callers` to request callers above the entry.

Python nodes have `precision: lsp`. There are no memory layouts or globals. Calls
through callbacks, dynamic attributes, or closures can be missing when Pyright
does not report them. Module-level callers are `module` nodes spanning the file.
Calls to known overloaded stub families can collapse into one unresolved target
whose `family` metadata records the overload evidence.

Increase `--lsp-timeout` for slower indexing and use `-v` to write `.hx/lsp.log`.
`--lsp-cmd 'pyright-langserver --stdio'` overrides the default command. Each
extraction starts a new server; there is no persistent LSP session across runs.
