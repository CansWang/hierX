"""hx command line. Phase 1: `hx extract`."""
from __future__ import annotations

import argparse
import os
import shlex
import sys

from . import __version__
from .frontends.base import FrontendError, EntryNotFound


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hx", description="Function-scoped structure extractor.")
    p.add_argument("--version", action="version", version=f"hx {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="walk the call hierarchy from <file>:<symbol> and write graph.json")
    e.add_argument("entry", help="<file>:<symbol>, e.g. src/dma.c:dma_start")
    e.add_argument("--root", default=".", help="project root (ids are relative to it)")
    e.add_argument("--compile-commands", help="compile_commands.json or the directory containing it")
    g = e.add_mutually_exclusive_group()
    g.add_argument("--depth", type=int, default=3, help="callee depth to expand (default 3)")
    g.add_argument("--all", action="store_true", help="no depth limit")
    e.add_argument("--type-depth", type=int, default=2, help="how deep to expand nested struct fields (default 2)")
    e.add_argument("--include-callers", action="store_true", help="also walk callers of the entry (negative depth)")
    e.add_argument("--include-system", action="store_true", help="expand functions/types from system headers")
    e.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="skip definitions whose path matches (repeatable)")
    e.add_argument("--max-nodes", type=int, help="safety cap on expanded functions")
    e.add_argument("--extra-arg", action="append", default=[], metavar="ARG", help="extra compiler arg for every TU (repeatable)")
    e.add_argument("--resource-dir", help="clang resource dir (auto-detected from `clang -print-resource-dir`)")
    e.add_argument("--jobs", "-j", type=int, help="parallel parse workers (default: cpus-1)")
    e.add_argument("--no-cache", action="store_true", help="ignore and do not write .hx/cache")
    e.add_argument("--lang", default="auto", help="auto (by extension) | c | cpp | sv | rust | python | go")
    sv = e.add_argument_group("SystemVerilog (verilator)")
    sv.add_argument("--sv-file", action="append", default=[], metavar="GLOB", help="source glob relative to root (repeatable); default: a *.f at root, else **/*.sv + **/*.v")
    sv.add_argument("-f", "--filelist", help="verilator -f file list")
    sv.add_argument("--top", help="top module (default: inferred from the entry symbol)")
    sv.add_argument("--verilator", default="verilator", help="verilator executable")
    lsp = e.add_argument_group("LSP languages (rust-analyzer, pyright, gopls)")
    lsp.add_argument("--lsp-cmd", help="language server command line, e.g. 'rust-analyzer' or 'pyright-langserver --stdio'")
    lsp.add_argument("--lsp-timeout", type=float, default=90.0, help="seconds to wait for the server to index (default 90)")
    e.add_argument("-o", "--output", help="output path (default <root>/.hx/graph.json)")
    e.add_argument("-v", "--verbose", action="store_true")
    sv = sub.add_parser("serve", help="open the browser viewer on a graph.json, with editable annotations")
    sv.add_argument("graph", nargs="?", help="graph.json (default .hx/graph.json)")
    sv.add_argument("--root", help="project root for source snippets (default: graph's root)")
    sv.add_argument("--annotations", help="annotations.json (default: next to the graph)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--open", action="store_true", help="open the browser")
    sv.add_argument("--no-extract", action="store_true", help="disable the re-extract button/endpoint")

    ex = sub.add_parser("export", help="write a standalone viewer HTML with graph + annotations inlined")
    ex.add_argument("graph", nargs="?", help="graph.json (default .hx/graph.json)")
    ex.add_argument("--annotations", help="annotations.json (default: next to the graph)")
    ex.add_argument("-o", "--output", help="output HTML (default: <graph dir>/view.html)")
    return p


def _default_graph(path: str | None) -> str:
    return os.path.abspath(path or os.path.join(".hx", "graph.json"))


def cmd_serve(a: argparse.Namespace) -> int:
    graph = _default_graph(a.graph)
    if not os.path.exists(graph):
        print(f"hx: {graph} does not exist; run `hx extract` first or pass the graph path", file=sys.stderr)
        return 2
    try:
        import uvicorn
        from .serve.app import create_app
    except ImportError as e:
        print(f"hx: serve needs fastapi and uvicorn ({e}); pip install 'fastapi uvicorn'", file=sys.stderr)
        return 2
    app = create_app(graph, a.annotations, a.root, allow_extract=not a.no_extract)
    url = f"http://{a.host}:{a.port}/"
    print(f"hx viewer   {url}")
    print(f"graph       {graph}")
    print(f"annotations {app.state.hx.ann_path}")
    if a.open:
        import webbrowser
        webbrowser.open(url)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
    return 0


def cmd_export(a: argparse.Namespace) -> int:
    from .export import export_file
    graph = _default_graph(a.graph)
    if not os.path.exists(graph):
        print(f"hx: {graph} does not exist; run `hx extract` first or pass the graph path", file=sys.stderr)
        return 2
    out = a.output or os.path.join(os.path.dirname(graph), "view.html")
    export_file(graph, out, a.annotations)
    print(f"output      {out}  ({os.path.getsize(out) // 1024} KB)")
    return 0


def cmd_extract(a: argparse.Namespace) -> int:
    from .api import extract
    root = os.path.abspath(a.root)
    try:
        graph = extract(a.entry, root=root, compile_commands=a.compile_commands,
                        depth=None if a.all else a.depth, type_depth=a.type_depth,
                        include_callers=a.include_callers, include_system=a.include_system,
                        exclude=a.exclude, max_nodes=a.max_nodes, extra_args=a.extra_arg,
                        resource_dir=a.resource_dir, jobs=a.jobs, use_cache=not a.no_cache,
                        verbose=a.verbose, lang=a.lang, sv_files=a.sv_file, filelist=a.filelist, top=a.top,
                        verilator=a.verilator, lsp_cmd=shlex.split(a.lsp_cmd) if a.lsp_cmd else None,
                        lsp_timeout=a.lsp_timeout)
    except EntryNotFound as e:
        print(f"hx: {e}", file=sys.stderr)
        if e.suggestions:
            print("hx: did you mean: " + ", ".join(e.suggestions), file=sys.stderr)
        return 2
    except (FrontendError, ValueError) as e:
        print(f"hx: {e}", file=sys.stderr)
        return 2
    out = a.output or os.path.join(root, ".hx", "graph.json")
    graph.save(out)
    idx = graph.meta.get("index", {})
    print(f"entry       {graph.entry}")
    print(f"nodes       {len(graph.nodes)}   edges {len(graph.edges)}   types {len(graph.types)}   "
          f"globals {len(graph.globals)}   unresolved {len(graph.unresolved)}")
    if idx.get("server"):
        print(f"server      {idx['server']}   ready in {idx.get('ready_seconds', '?')}s   ({len(graph.nodes)} functions resolved, precision lsp)")
    else:
        print(f"tus         {idx.get('tus', '?')} total, {idx.get('parsed', '?')} parsed, {idx.get('cached', '?')} cached, "
              f"{idx.get('tu_errors', 0)} failed, {idx.get('diagnostics', 0)} compile errors   ({idx.get('index_seconds', '?')}s)")
    if graph.meta.get("truncated"):
        print("note        graph truncated by --max-nodes")
    for note in graph.meta.get("notes", []):
        print(f"note        {note}")
    print(f"output      {out}")
    if a.verbose:
        for u in graph.unresolved:
            where = f"{u.loc.file}:{u.loc.line}" if u.loc else "?"
            print(f"  unresolved  {u.name:<30} {u.reason:<36} from {u.src} @ {where}")
        for err in graph.meta.get("tu_errors", []):
            print(f"  tu-error    {err['file']}: {err['error']}")
        for d in graph.meta.get("diagnostics", [])[:30]:
            print(f"  diag        {d.get('file')}:{d.get('line')}: {d['message']}")
    if idx.get("tu_errors"):
        print(f"warning     {idx['tu_errors']} translation unit(s) failed to parse; rerun with -v for details", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = _build_parser()
    a = p.parse_args(argv)
    if a.cmd == "extract":
        return cmd_extract(a)
    if a.cmd == "serve":
        return cmd_serve(a)
    if a.cmd == "export":
        return cmd_export(a)
    p.error(f"unknown command {a.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
