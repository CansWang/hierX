"""hx command line. Phase 1: `hx extract`."""
from __future__ import annotations

import argparse
import os
import shlex
import sys
import time

from . import __version__
from .frontends.base import FrontendError, EntryNotFound
from .paths import resolve_project, select_graph

_ROOT_HELP = ("project root (overrides discovery; default: first .github upward from the entry source, "
              "or from the run directory for commands without an entry; falls back to the run directory)")
_GRAPH_HELP = ("graph JSON file (default: run-directory .hx first, otherwise .hx at the first .github upward; "
               "graph.json preferred, then graphs/*.json excluding annotations.json)")
_ANNOTATIONS_HELP = "annotation file override (default: shared .hx/annotations.json for managed graphs; beside standalone graphs)"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hx", description="Function-scoped structure extractor.")
    p.add_argument("--version", action="version", version=f"hx {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="walk the call hierarchy from <file>:<symbol> and write graph.json")
    e.add_argument("entry", help="<file>:<symbol>, e.g. src/dma.c:dma_start")
    e.add_argument("--root", help=_ROOT_HELP)
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
    e.add_argument("--lang", default="auto", help="auto (by extension) | c | cpp | sv | rust | python | go | spice")
    sv = e.add_argument_group("SystemVerilog (verilator)")
    sv.add_argument("--sv-file", action="append", default=[], metavar="GLOB", help="source glob (run-relative with discovery, root-relative with --root; repeatable); default: a *.f at root, else **/*.sv + **/*.v")
    sv.add_argument("-f", "--filelist", help="verilator -f file list")
    sv.add_argument("--top", help="top module (default: inferred from the entry symbol)")
    sv.add_argument("--verilator", default="verilator", help="verilator executable")
    nl = e.add_argument_group("SPICE-family netlists (native parser; simulators only as optional oracles)")
    nl.add_argument("--dialect", default="auto", help="auto | spice | ngspice | xyce (HSPICE and Spectre are deferred)")
    nl.add_argument("--deck", help="top deck when the entry file is an include or library (default: the entry file; a `@name` entry whose line 1 is a dot-directive is read as a standalone library, line 1 kept)")
    nl.add_argument("--search-path", action="append", default=[], dest="search_paths", metavar="DIR", help="extra directory for .include/.lib resolution (repeatable)")
    lsp = e.add_argument_group("LSP languages (rust-analyzer, pyright, gopls)")
    lsp.add_argument("--lsp-cmd", help="language server command line, e.g. 'rust-analyzer' or 'pyright-langserver --stdio'")
    lsp.add_argument("--lsp-timeout", type=float, default=90.0, help="seconds to wait for the server to index (default 90)")
    e.add_argument("-o", "--output", help="standalone output path (default: per-entry .hx/graphs/ current file plus .hx/graph.json, with previous history)")
    e.add_argument("-v", "--verbose", action="store_true")
    sv = sub.add_parser("serve", help="open the browser viewer on a graph.json, with editable annotations")
    sv.add_argument("graph", nargs="?", help=_GRAPH_HELP)
    sv.add_argument("--root", help="project root for source snippets (default: graph's root)")
    sv.add_argument("--annotations", help=_ANNOTATIONS_HELP)
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--open", action="store_true", help="open the browser")
    sv.add_argument("--no-extract", action="store_true", help="disable the re-extract button/endpoint")

    tr = sub.add_parser("track", help="add an entry point to .hx/config.toml so `hx update`/`hx watch`/the hook re-extract it")
    tr.add_argument("entry", nargs="?", help="<file>:<symbol>")
    tr.add_argument("--root", help=_ROOT_HELP)
    tr.add_argument("--list", action="store_true", help="list tracked entries")
    tr.add_argument("--remove", action="store_true", help="remove the entry instead of adding it")
    track_help = {"--depth": "callee depth to expand (default 3)", "--type-depth": "how deep to expand nested struct fields (default 2)",
                  "--include-callers": "also walk callers of the entry", "--include-system": "expand functions/types from system headers",
                  "--exclude": "skip definitions whose path matches GLOB (repeatable)", "--max-nodes": "safety cap on expanded functions",
                  "--extra-arg": "extra compiler arg for every TU (repeatable)", "--compile-commands": "compile_commands.json or the directory containing it",
                  "--lang": "auto (by extension) | c | cpp | sv | rust | python | go | spice", "--sv-file": "SystemVerilog source glob (repeatable)",
                  "-f": "verilator -f file list", "--top": "top module (default: inferred from the entry symbol)",
                  "--lsp-cmd": "language server command line", "--lsp-timeout": "seconds to wait for the server to index (default 90)",
                  "--dialect": "netlist dialect: auto | spice | ngspice | xyce", "--deck": "top deck when the entry file is an include or library",
                  "--search-path": "extra directory for .include/.lib resolution (repeatable)"}
    for flag, kw in (("--depth", dict(type=int)), ("--type-depth", dict(type=int)), ("--include-callers", dict(action="store_true")),
                     ("--include-system", dict(action="store_true")), ("--exclude", dict(action="append", default=[], metavar="GLOB")),
                     ("--max-nodes", dict(type=int)), ("--extra-arg", dict(action="append", default=[], metavar="ARG")), ("--compile-commands", {}),
                     ("--lang", {}), ("--sv-file", dict(action="append", default=[], metavar="GLOB")), ("-f", dict(dest="filelist")), ("--top", {}),
                     ("--lsp-cmd", {}), ("--lsp-timeout", dict(type=float)),
                     ("--dialect", {}), ("--deck", {}), ("--search-path", dict(action="append", default=[], dest="search_paths", metavar="DIR"))):
        tr.add_argument(flag, help=track_help[flag], **kw)

    up = sub.add_parser("update", help="re-extract tracked entries, snapshot the previous graphs and print what changed")
    up.add_argument("entries", nargs="*", help="only these entries (default: all tracked)")
    up.add_argument("--root", help=_ROOT_HELP)
    up.add_argument("--quiet", action="store_true", help="print one line per entry instead of the full diff")
    up.add_argument("--json", action="store_true", help="print the diff JSON documents")
    up.add_argument("--hook", action="store_true", help="hook mode: read and ignore stdin, never exit non-zero")

    wa = sub.add_parser("watch", help="poll sources and run `hx update` after each quiet period")
    wa.add_argument("--root", help=_ROOT_HELP)
    wa.add_argument("--interval", type=float, help="poll interval seconds (config: watch.interval, default 2)")
    wa.add_argument("--debounce", type=float, help="quiet seconds before updating (config: watch.debounce, default 1)")
    wa.add_argument("--once", action="store_true", help="run one update and exit")
    wa.add_argument("--no-initial", action="store_true", help="do not update at startup, only on change")

    df = sub.add_parser("diff", help="structural diff between two graphs, or an entry against its history")
    df.add_argument("old", nargs="?", help="old graph.json (or omit with --entry)")
    df.add_argument("new", nargs="?", help="new graph.json")
    df.add_argument("--entry", help="tracked entry: diff its current graph against history")
    df.add_argument("--since", default="prev", help="history point for --entry: prev | <snapshot ts> | <ISO time>")
    df.add_argument("--root", help=_ROOT_HELP)
    df.add_argument("--format", choices=["md", "json"], default="md")
    df.add_argument("-o", "--output")
    df.add_argument("--exit-code", action="store_true", help="exit 1 when there are changes")

    hk = sub.add_parser("hook", help="Claude Code hook that runs `hx update` after each agent turn")
    hk.add_argument("action", choices=["print", "install"])
    hk.add_argument("--root", help=_ROOT_HELP)
    hk.add_argument("--event", default="Stop", choices=["Stop", "PostToolUse"])
    hk.add_argument("--command", default="hx update --quiet --hook")
    hk.add_argument("--settings-dir", help="directory holding settings.json (default <root>/.claude)")

    mc = sub.add_parser("mcp", help="run the MCP server (stdio) so agents can query graphs instead of grepping")
    mc.add_argument("--root", help=_ROOT_HELP)
    mc.add_argument("--print-config", action="store_true", help="print the .mcp.json / `claude mcp add` snippet")

    mg = sub.add_parser("migrate", help="upgrade hx/1, hx/2 or hx/3: re-extract tracked entries and migrate annotations to hx/4")
    mg.add_argument("--root", help=_ROOT_HELP)
    mg.add_argument("--keep-history", type=int, default=None, metavar="N",
                    help="previous graphs to keep per entry when the migrated graphs are committed (default: watch.history from .hx/config.toml, 20)")
    mg.set_defaults(func=cmd_migrate)

    nl = sub.add_parser("netlist", help="SPICE-family netlist utilities (optional simulator oracles)")
    nls = nl.add_subparsers(dest="netlist_cmd", required=True)
    ck = nls.add_parser("check", help="cross-check a deck's structure (paths, arity, nets, models, references) with a simulator oracle")
    ck.add_argument("entry", help="<deck>:. (whole deck); <deck>:<instance path> (ngspice compares that subtree); <file>:@definition with deck "
                                  "context (ngspice compares once per unguarded instance). xyce and xdm always check the whole deck")
    ck.add_argument("--oracle", choices=["ngspice", "xyce", "xdm"], default="ngspice",
                    help="ngspice: paths, arity, nets, models, references from `listing expand`; xyce: syntax/topology, device-family counts, "
                         "exposed net names; xdm: top-level primitive inventory. The report's `scope` line says what was compared")
    ck.add_argument("--ngspice", help="ngspice executable (default: PATH or HX_TOOL_NGSPICE)")
    ck.add_argument("--xyce", help="Xyce executable (or HX_TOOL_XYCE)")
    ck.add_argument("--xdm", help="XDM executable (or HX_TOOL_XDM)")
    ck.add_argument("--root", help=_ROOT_HELP)
    ck.add_argument("--dialect", default="auto", help="auto | spice | ngspice | xyce (with --oracle xyce|xdm, auto means xyce; an explicit dialect is kept)")
    ck.add_argument("--deck", help="top deck when the entry file is an include or library")
    ck.add_argument("--search-path", action="append", default=[], dest="search_paths", metavar="DIR")
    ck.add_argument("--json", action="store_true", help="print the full report as JSON (includes the rendered closure)")
    ck.add_argument("--limit", type=int, default=20, help="mismatches to print (default 20)")
    ck.add_argument("--timeout", type=float, default=120.0, help="seconds before the simulator run is abandoned as `oracle unavailable` (default 120)")

    for name in ("net", "uses"):
        q = nls.add_parser(name, help="query connectivity or declaration users in a saved graph")
        q.add_argument("target", help="net key/name" if name == "net" else "definition/model key/name")
        q.add_argument("--graph", help=_GRAPH_HELP)
        q.add_argument("--root", help=_ROOT_HELP)
        q.add_argument("--json", action="store_true")
        q.add_argument("--limit", type=int, default=60)
        if name == "net":
            q.add_argument("--node", default="", help="occurrence ID for guarded binding context")
        else:
            q.add_argument("--kind", required=True, choices=["definition", "model"])

    ex = sub.add_parser("export", help="write a standalone viewer HTML with graph + annotations inlined")
    ex.add_argument("graph", nargs="?", help=_GRAPH_HELP)
    ex.add_argument("--annotations", help=_ANNOTATIONS_HELP)
    ex.add_argument("-o", "--output", help="output HTML (default: <graph dir>/view.html)")
    from .architecture.cli import add_parser
    add_parser(sub)
    return p


def _default_graph(path: str | None) -> str:
    return select_graph(path)


def cmd_serve(a: argparse.Namespace) -> int:
    try:
        graph = _default_graph(a.graph)
    except (ValueError, OSError) as e:
        print(f"hx: {e}", file=sys.stderr)
        return 2
    try:
        import uvicorn
        from .serve.app import create_app
    except ImportError as e:
        print(f"hx: serve needs fastapi and uvicorn ({e}); pip install 'fastapi uvicorn'", file=sys.stderr)
        return 2
    try:
        app = create_app(graph, a.annotations, a.root, allow_extract=not a.no_extract)
    except (ValueError, OSError) as e:
        print(f"hx: {e}", file=sys.stderr)
        return 2
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
    try:
        graph = _default_graph(a.graph)
    except (ValueError, OSError) as e:
        print(f"hx: {e}", file=sys.stderr)
        return 2
    out = a.output or os.path.join(os.path.dirname(graph), "view.html")
    try:
        export_file(graph, out, a.annotations)
    except (ValueError, OSError) as e:
        print(f"hx: {e}", file=sys.stderr)
        return 2
    print(f"output      {out}  ({os.path.getsize(out) // 1024} KB)")
    return 0


def cmd_track(a: argparse.Namespace) -> int:
    from . import project
    root = os.path.abspath(a.root)
    if a.list or not a.entry:
        cfg = project.load_config(root)
        if not cfg["entries"]:
            print("no tracked entries (add one: hx track src/main.c:app_run --depth 3)")
        for e in cfg["entries"]:
            opts = ", ".join(f"{k}={v}" for k, v in e.items() if k != "entry")
            print(f"{e['entry']:<48} {opts}")
        return 0
    if a.remove:
        print("removed" if project.untrack(root, a.entry) else "not tracked", a.entry)
        return 0
    table = project.track(root, a.entry, depth=a.depth, type_depth=a.type_depth, include_callers=a.include_callers or None,
                          include_system=a.include_system or None, exclude=a.exclude, max_nodes=a.max_nodes, extra_args=a.extra_arg,
                          compile_commands=a.compile_commands, lang=a.lang, sv_files=a.sv_file, filelist=a.filelist, top=a.top,
                          lsp_cmd=shlex.split(a.lsp_cmd) if a.lsp_cmd else None, lsp_timeout=a.lsp_timeout,
                          dialect=a.dialect, deck=a.deck, search_paths=a.search_paths)
    print(f"tracking    {table['entry']}  ({project.config_path(root)})")
    return 0


def cmd_update(a: argparse.Namespace) -> int:
    from . import project
    if a.hook:
        try:
            sys.stdin.read()
        except Exception:  # noqa: BLE001
            pass
    try:
        results = project.update(a.root, a.entries or None, progress=None if a.quiet else (lambda m: print(m, file=sys.stderr)))
    except Exception as e:  # noqa: BLE001
        print(f"hx update failed: {e}", file=sys.stderr)
        return 0 if a.hook else 2
    if a.json:
        import json
        print(json.dumps([{"entry": r.entry, "graph": r.graph_path, "previous": r.previous, "error": r.error, "diff": r.diff} for r in results], indent=1))
    elif a.quiet:
        print(project.summarize(results))
    else:
        for r in results:
            print(r.markdown.rstrip())
            print()
        print(f"written     {os.path.join(project.hx_dir(a.root), 'last-diff.md')}")
    return 0


def cmd_watch(a: argparse.Namespace) -> int:
    from . import project
    root = os.path.abspath(a.root)
    cfg = project.load_config(root)
    if not cfg["entries"]:
        print("hx: nothing tracked; run `hx track <file>:<symbol>` first", file=sys.stderr)
        return 2

    def report(results):
        print(time.strftime("%H:%M:%S"), project.summarize(results).replace("\n", "\n         "))
        sys.stdout.flush()

    if a.once:
        report(project.update(root))
        return 0
    print(f"hx watch    {len(cfg['entries'])} entr{'y' if len(cfg['entries']) == 1 else 'ies'}, every {a.interval or cfg['watch'].get('interval', 2.0)}s (Ctrl-C to stop)")
    try:
        project.watch(root, interval=a.interval, debounce=a.debounce, on_update=report, run_first=not a.no_initial)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_diff(a: argparse.Namespace) -> int:
    import json
    from . import project
    from .diff import diff_graphs, render_markdown
    if a.entry:
        root = os.path.abspath(a.root)
        new_path = project.graph_path(root, a.entry)
        if not os.path.exists(new_path):
            print(f"hx: no graph for {a.entry}; run `hx update {a.entry}` first", file=sys.stderr)
            return 2
        try:
            h = project.resolve_history(root, a.entry, a.since)
        except (OSError, ValueError) as e:
            print(f"hx: {e}", file=sys.stderr)
            return 2
        if not h:
            print(f"hx: no history for {a.entry} yet (snapshots appear after the second `hx update`)", file=sys.stderr)
            return 2
        old_path, title = h["path"], f"{a.entry} since {h['ts']}"
    else:
        if not (a.old and a.new):
            print("hx: diff needs OLD NEW graph files, or --entry", file=sys.stderr)
            return 2
        old_path, new_path, title = a.old, a.new, None
    old, new = project.load_graph(old_path), project.load_graph(new_path)
    d = diff_graphs(old, new)
    out = json.dumps(d, indent=1) if a.format == "json" else render_markdown(d, new, title=title)
    if a.output:
        os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(out if out.endswith("\n") else out + "\n")
        print(f"written     {a.output}")
    else:
        print(out, end="" if out.endswith("\n") else "\n")
    return 1 if a.exit_code and d["summary"]["any"] else 0


def cmd_migrate(a: argparse.Namespace) -> int:
    from . import project
    res = project.migrate(os.path.abspath(a.root), keep_history=a.keep_history, progress=lambda m: print(f"migrate     {m}"))
    for e in res["entries"]:
        print(f"entry       {e['entry']}  was {e.get('was_schema') or 'new'}  renamed {e['renamed']}  unmapped {e['unmapped']}")
    for f in res["failed"]:
        print(f"FAILED      {f['entry']}: {f['error']}", file=sys.stderr)
    if res["status"] == "failed":
        print("hx: nothing was written (graphs, history, annotations and backups are unchanged); fix the failures and re-run", file=sys.stderr)
        return 2
    for k, v in list(res["ambiguous"].items())[:10]:
        print(f"ambiguous   {k} -> {', '.join(v)} (not rewritten)")
    for u in res["unmapped"][:10]:
        print(f"unmapped    {u['id']}  ({u['reason']})")
    if len(res["unmapped"]) > 10:
        print(f"            … {len(res['unmapped']) - 10} more unmapped")
    ann = res.get("annotations") or {}
    print(f"annotations {ann.get('status', 'none')}  renamed {ann.get('renamed', 0)}  conflicts {len(ann.get('conflicts', []))}"
          + (f"  backup {ann['backup']}" if ann.get("backup") else ""))
    print(f"status      {res['status']}")
    return 0


def cmd_hook(a: argparse.Namespace) -> int:
    import json
    from . import project
    if a.action == "print":
        print(json.dumps(project.hook_snippet(a.event, a.command), indent=2))
        return 0
    try:
        path, added = project.install_hook(a.root, a.event, a.command, a.settings_dir)
    except (ValueError, OSError) as e:
        print(f"hx: cannot install the hook: {e}", file=sys.stderr)
        return 2
    print(("installed   " if added else "already set ") + f"{a.event} hook → {a.command}  ({path})")
    return 0


def cmd_mcp(a: argparse.Namespace) -> int:
    import json
    root = os.path.abspath(a.root)
    if a.print_config:
        print(json.dumps({"mcpServers": {"hx": {"command": "hx", "args": ["mcp", "--root", root]}}}, indent=2))
        print(f"\n# or: claude mcp add hx -- hx mcp --root {root}", file=sys.stderr)
        return 0
    try:
        from .mcp_server import build_server
    except ImportError as e:
        print(f"hx: the MCP server needs the `mcp` package ({e}); pip install 'mcp>=2'", file=sys.stderr)
        return 2
    try:
        server = build_server(root)
    except (ValueError, OSError) as e:
        print(f"hx: {e}", file=sys.stderr)
        return 2
    server.run(transport="stdio")
    return 0


def cmd_netlist(a: argparse.Namespace) -> int:
    import json
    if a.netlist_cmd in ("net", "uses"):
        from .netlist.query import get_net, uses, format_result
        from .graphio import load_graph_dict
        try:
            from pathlib import Path
            path = a.graph or select_graph(None, cwd=Path(a.root))
            graph = load_graph_dict(path)
            result = (get_net(graph, a.target, node=a.node, limit=a.limit) if a.netlist_cmd == "net" else
                      uses(graph, a.target, kind=a.kind, limit=a.limit))
            print(json.dumps(result, indent=2) if a.json else format_result(result))
            return 0
        except (OSError, ValueError) as e:
            print(f"hx: {e}", file=sys.stderr)
            return 2
    from .netlist.check import check_ngspice, format_report
    root = os.path.abspath(a.root)
    try:
        if a.oracle == "ngspice":
            report = check_ngspice(a.entry, root=root, exe=a.ngspice, dialect=a.dialect, deck=a.deck, search_paths=a.search_paths, timeout=a.timeout)
        else:
            from .netlist.xyce import check_external
            report = check_external(a.entry, root=root, oracle=a.oracle, exe=getattr(a, a.oracle),
                                    dialect=a.dialect, deck=a.deck, search_paths=a.search_paths, timeout=a.timeout)
    except EntryNotFound as e:
        print(f"hx: {e}", file=sys.stderr)
        if e.suggestions:
            print("hx: did you mean: " + ", ".join(e.suggestions), file=sys.stderr)
        return 2
    except (FrontendError, ValueError) as e:
        print(f"hx: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(report, indent=1))
    else:
        print(format_report(report, a.limit))
    return {"agree": 0, "mismatch": 1}.get(report["status"], 2)


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
                        lsp_timeout=a.lsp_timeout, dialect=a.dialect, deck=a.deck, search_paths=a.search_paths)
    except EntryNotFound as e:
        print(f"hx: {e}", file=sys.stderr)
        if e.suggestions:
            print("hx: did you mean: " + ", ".join(e.suggestions), file=sys.stderr)
        return 2
    except (FrontendError, ValueError) as e:
        print(f"hx: {e}", file=sys.stderr)
        return 2
    out = a.output or os.path.join(root, ".hx", "graph.json")
    from . import project
    try:
        project.save_extraction(root, a.entry, graph, output=a.output,
                                archive=not bool(a.output), refresh_default=not bool(a.output))
    except (OSError, ValueError) as e:
        print(f"hx: {e}", file=sys.stderr)
        return 2
    idx = graph.meta.get("index", {})
    print(f"entry       {graph.entry}")
    print(f"nodes       {len(graph.nodes)}   edges {len(graph.edges)}   types {len(graph.types)}   "
          f"globals {len(graph.globals)}   unresolved {len(graph.unresolved)}")
    if idx.get("server"):
        print(f"server      {idx['server']}   ready in {idx.get('ready_seconds', '?')}s   ({len(graph.nodes)} functions resolved, precision lsp)")
    elif idx.get("dialect"):
        print(f"files       {idx.get('files', '?')} total, {idx.get('parsed', '?')} parsed, {idx.get('cached', '?')} cached, "
              f"{idx.get('diagnostics', 0)} diagnostics ({idx.get('errors', 0)} errors)   dialect {idx['dialect']} ({idx.get('index_seconds', '?')}s)")
    else:
        print(f"tus         {idx.get('tus', '?')} total, {idx.get('parsed', '?')} parsed, {idx.get('cached', '?')} cached, "
              f"{idx.get('tu_errors', 0)} failed, {idx.get('diagnostics', 0)} errors, {idx.get('warnings', 0)} warnings   ({idx.get('index_seconds', '?')}s)")
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
            print(f"  diag        {d.get('file')}:{d.get('line')}: {d.get('code', '') + ': ' if d.get('code') else ''}{d['message']}")
    if idx.get("tu_errors"):
        print(f"warning     {idx['tu_errors']} translation unit(s) failed to parse; rerun with -v for details", file=sys.stderr)
    return 0


def _resolve_project_args(a: argparse.Namespace) -> None:
    """Resolve CLI defaults once; leave programmatic roots and viewer overrides alone."""
    if a.cmd in {"serve", "export", "arch"}:
        return
    entry_command = a.cmd in {"extract", "netlist", "diff"} or (a.cmd == "track" and not a.list)
    entries = a.entries if a.cmd == "update" else ([a.entry] if entry_command and getattr(a, "entry", None) else [])
    explicit_root = a.root is not None
    a.root, normalized = resolve_project(a.root, entries)
    if a.cmd == "update":
        a.entries = normalized
    elif entries:
        a.entry = normalized[0]
    if not explicit_root:
        # Frontends interpret several options relative to root and may replay
        # them in another process/cwd. Preserve the paths the CLI user supplied.
        for key in ("compile_commands", "resource_dir", "filelist", "deck"):
            value = getattr(a, key, None)
            if value:
                setattr(a, key, os.path.abspath(value))
        for key in ("sv_file", "search_paths"):
            if hasattr(a, key):
                setattr(a, key, [os.path.abspath(value) for value in getattr(a, key)])
        for key in ("verilator", "ngspice", "xyce", "xdm"):
            value = getattr(a, key, None)
            if value and os.path.dirname(value):
                setattr(a, key, os.path.abspath(value))
        if getattr(a, "lsp_cmd", None):
            command = shlex.split(a.lsp_cmd)
            if command and os.path.dirname(command[0]):
                command[0] = os.path.abspath(command[0])
                a.lsp_cmd = shlex.join(command)


def main(argv: list[str] | None = None) -> int:
    p = _build_parser()
    a = p.parse_args(argv)
    try:
        _resolve_project_args(a)
    except (ValueError, OSError) as e:
        print(f"hx: {e}", file=sys.stderr)
        if a.cmd == "update" and a.hook:
            try:
                sys.stdin.read()
            except Exception:  # noqa: BLE001 - preserve the hook's non-failing policy
                pass
            return 0
        return 2
    if a.cmd == "extract":
        return cmd_extract(a)
    if a.cmd == "arch":
        from .architecture.cli import run
        return run(a)
    if a.cmd == "serve":
        return cmd_serve(a)
    if a.cmd == "export":
        return cmd_export(a)
    if a.cmd == "track":
        return cmd_track(a)
    if a.cmd == "update":
        return cmd_update(a)
    if a.cmd == "watch":
        return cmd_watch(a)
    if a.cmd == "diff":
        return cmd_diff(a)
    if a.cmd == "hook":
        return cmd_hook(a)
    if a.cmd == "mcp":
        return cmd_mcp(a)
    if a.cmd == "migrate":
        return cmd_migrate(a)
    if a.cmd == "netlist":
        return cmd_netlist(a)
    p.error(f"unknown command {a.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
