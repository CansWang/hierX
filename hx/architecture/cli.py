"""CLI boundary for authored architecture; never uses extraction discovery."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from .presentation import build_html, payload
from .service import load_architecture


def add_parser(sub):
    arch = sub.add_parser("arch", help="inspect, preview and export D2-authored architecture")
    commands = arch.add_subparsers(dest="arch_cmd", required=True)
    for name, help_text in (("inspect", "interpret D2 and report blocks, ports and connections"),
                            ("serve", "preview architecture with optional source navigation"),
                            ("export", "export an offline architecture diagram as HTML")):
        parser = commands.add_parser(name, help=help_text)
        parser.add_argument("design", help="D2 architecture file")
        parser.add_argument("--root", help="D2 import project root (default: design's directory)")
        parser.add_argument("--graph", help="one explicit saved graph for exact code-link resolution")
        parser.add_argument("--d2-bridge", help="hx-d2-bridge executable override (or HX_TOOL_D2_BRIDGE)")
        if name == "inspect":
            parser.add_argument("--json", action="store_true", help="print the normalized hx-arch/1 document")
        elif name == "export":
            parser.add_argument("-o", "--output", required=True, help="standalone HTML destination")
            parser.add_argument("--code-url", help="absolute http(s) Hx viewer URL; no source is embedded")
        else:
            parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
            parser.add_argument("--port", type=int, default=8766, help="HTTP port (default 8766)")
            parser.add_argument("--open", action="store_true", help="open the architecture preview in a browser")


def run(args) -> int:
    try:
        doc = load_architecture(args.design, root=args.root, graph=args.graph, bridge=args.d2_bridge)
        if args.arch_cmd == "inspect" and args.json:
            print(json.dumps(doc.to_dict(), ensure_ascii=False))
        else:
            for d in doc.diagnostics:
                print(f'{d["severity"]}: {d["code"]}: {d["subject"]}: {d["message"]}', file=sys.stderr)
        if not doc.valid:
            return 1
        if args.arch_cmd == "inspect":
            if not args.json:
                print(f"architecture {len(doc.blocks)} blocks, {len(doc.ports)} ports, {len(doc.connections)} connections; authored intent only")
            return 0
        if args.arch_cmd == "export":
            target = Path(args.output).resolve()
            project = Path(args.root).resolve() if args.root else Path(args.design).resolve().parent
            protected = {Path(args.design).resolve()} | {(project / p["file"]).resolve() for p in doc.inputs}
            if target in protected or (target.exists() and any(p.exists() and os.path.samefile(target, p) for p in protected)):
                raise ValueError("output must not overwrite a design, import or saved graph")
            html = build_html(doc, code_url=args.code_url)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html, encoding="utf-8")
            print(f"architecture HTML {target}")
            return 0
        import uvicorn
        from .serve import create_architecture_app
        app = create_architecture_app(args.design, root=args.root, graph=args.graph, bridge=args.d2_bridge)
        url = f"http://{args.host}:{args.port}/architecture"
        print(f"architecture viewer {url}")
        if args.open:
            import webbrowser
            webbrowser.open(url)
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
        return 0
    except (OSError, ValueError) as exc:
        print(f"hx arch: {exc}", file=sys.stderr)
        return 2
