# Contribute documentation

From an activated environment at the repository root:

```bash
python -m pip install -e '.[dev,docs]'
mkdocs serve
mkdocs build --strict
python -m pytest -q tests/test_docs.py tests/test_tutorials.py
```

`mkdocs serve` previews on port 8000; `mkdocs build --strict` writes `site/`.
Generated HTML is ignored by Git. The CI docs job installs only hx, the development
dependencies, and documentation tools: it needs no external language toolchains.
Language tutorial smoke tests run in the existing toolchain job.

## Keep instructions executable

Tutorial inputs come from `tests/fixtures`; `examples/prepare.py` copies them into
new workspaces. Avoid adding another copy of a fixture just for the documentation.
The Python scripting tutorial includes `examples/inspect_graph.py` at build time,
so its displayed code and executed code stay identical.

Selected shell blocks use `<!-- hx:test NAME -->` immediately before a `bash`
fence. Tests execute those exact blocks in a fresh prepared workspace with the
installed hx command on PATH. Keep interactive commands, installations, and
machine-specific paths outside these blocks. Every marked block is exercised by
the tutorial tests; use a timeout when adding a long-running integration check.

The optional ngspice tutorial check uses the existing `vendor_tool` test marker,
so a machine without ngspice can still verify native extraction. Enable it as a
requirement with `HX_REQUIRE_VENDOR_TOOLS=ngspice`. The project's strict
`HX_REQUIRE_TOOLS=1` policy continues to apply to language frontend checks.

## Keep references tied to source

The build hook renders all argparse command help without running extraction and
copies the current graph JSON schema into the site. Python reference directives
have explicit member lists; add an object deliberately and document its return
value, errors, and effects before making it part of the reference. A Python API
addition does not require exposing internal frontend helpers.

HTTP/MCP inventory tests compare reference headings and argument names against
the actual routes and tool schemas. Update prose and examples when those
interfaces change. Use relative Markdown links between pages, and keep the README
links to the main learning paths current. Navigation, missing links, anchors, and
unresolved Python references fail the strict build. External web links are not
checked by the offline build.

Document implemented behavior rather than roadmap claims. Keep optional tools
separate from prerequisites for extraction. When adding a frontend or dialect,
update installation, precision/limitations, examples, reference, and coverage.
