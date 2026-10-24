"""Local examples harness. Authored intent and navigation records stay separate."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import webbrowser

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))


class ExampleError(ValueError):
    """An example input or local prerequisite needs attention."""


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class Examples:
    def __init__(self, base=HERE, bridge=None):
        self.base = Path(base).resolve()
        self.generated = self.base / ".generated"
        self.bridge = bridge
        self.cases = {
            c["id"]: c for c in read_json(self.base / "examples.json")["examples"]
        }

    def selected(self, name):
        if name == "all":
            return list(self.cases.values())
        if name not in self.cases:
            raise ExampleError(f"Unknown example {name!r}; run ./run.sh list")
        return [self.cases[name]]

    def output(self, relative):
        # Only this harness's ignored directory owns generated files.
        if self.generated.is_symlink():
            raise ExampleError(
                ".generated must be a real local directory, not a symlink"
            )
        target = self.generated / relative
        if not target.resolve().is_relative_to(self.generated.resolve()):
            raise ExampleError(f"Generated output escapes .generated: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def write_json(self, relative, data):
        from hx.fsutil import atomic_write

        path = self.output(relative)
        atomic_write(str(path), json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return path

    def validate_sources(self):
        manifest = read_json(self.base / "sources/manifest.json")
        source_root = (self.base / "sources").resolve()
        declared = {}
        for repo, origin in manifest["repositories"].items():
            for record in origin["files"]:
                path = source_root / record["file"]
                if not path.resolve().is_relative_to(source_root):
                    raise ExampleError(
                        f"Snapshot escapes source root: {record['file']}"
                    )
                if not path.is_file():
                    raise ExampleError(f"Missing pinned snapshot: {record['file']}")
                if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                    raise ExampleError(
                        f"Snapshot SHA-256 mismatch: {record['file']}; restore the pinned file"
                    )
                declared[record["file"]] = (repo, record)
        records = read_json(self.base / "navigation.json")["records"]
        nodes = {}
        for record in records:
            node = record["node"]
            loc = node["loc"]
            if (
                loc["file"] not in declared
                or declared[loc["file"]][1]["kind"] != "source"
            ):
                raise ExampleError(
                    f"Navigation target is outside pinned source files: {loc['file']}"
                )
            if declared[loc["file"]][0] != record["repository"]:
                raise ExampleError(f"Navigation repository mismatch: {node['id']}")
            lang, original = record["original_id"].split(":", 1)
            if node["id"] != f"{lang}:{record['repository']}/{original}":
                raise ExampleError(
                    f"Navigation ID was not rebased consistently: {node['id']}"
                )
            text = (source_root / loc["file"]).read_text(encoding="utf-8").splitlines()
            start, end = loc["line"], loc.get("end_line") or loc["line"]
            if not 1 <= start <= end <= len(text):
                raise ExampleError(f"Invalid source range: {node['id']}")
            if node["name"] not in "\n".join(text[start - 1 : min(start + 12, end)]):
                raise ExampleError(
                    f"Declaration does not match source range: {node['id']}"
                )
            if node["id"] in nodes:
                raise ExampleError(f"Duplicate navigation declaration: {node['id']}")
            nodes[node["id"]] = node
        return nodes

    def prepare(self):
        nodes = self.validate_sources()
        # This is a declaration catalog, never an extracted multi-repository graph.
        graph = {
            "schema": "hx/4",
            "generated": datetime.now(timezone.utc).isoformat(),
            "root": str(self.base / "sources"),
            "lang": "mixed",
            "entry": next(iter(nodes)),
            "nodes": nodes,
            "types": {},
            "globals": {},
            "edges": [],
            "unresolved": [],
            "meta": {
                "notes": [
                    "Navigation-only declaration subset; authored D2 arrows are not extracted relationships."
                ],
                "evidence_limits": [
                    "navigation-only",
                    "relations-omitted",
                    "selected-declarations-only",
                ],
            },
        }
        path = self.write_json(".hx/graph.json", graph)
        return path

    def document(self, case, graph):
        from hx.architecture import load_architecture

        return load_architecture(
            str(self.base / "cases" / case["id"] / "main.d2"),
            root=str(self.base / "cases"),
            graph=str(graph),
            bridge=self.bridge,
        )

    @staticmethod
    def verify(case, doc):
        """Compare production interpretation against checked-in independent expectations."""
        errors = [f"{d['code']}: {d['message']}" for d in doc.diagnostics]
        if not doc.valid:
            errors.append("Architecture is invalid")
        blocks = {(b["id"], b["parent"]) for b in doc.blocks}
        expected_blocks = {(b["id"], b["parent"]) for b in case["blocks"]}
        ports = {(p["id"], p["block"], p["direction"]) for p in doc.ports}
        expected_ports = {(p["id"], p["block"], p["direction"]) for p in case["ports"]}
        edges = Counter(
            (e["source"], e["target"], e["kind"], e["label"]) for e in doc.connections
        )
        expected_edges = Counter(
            (e["source"], e["target"], e["kind"], e["label"])
            for e in case["connections"]
        )
        for label, observed, expected in [
            ("blocks", blocks, expected_blocks),
            ("ports", ports, expected_ports),
            ("connections", edges, expected_edges),
        ]:
            if observed != expected:
                errors.append(
                    f"Unexpected {label}: missing={expected - observed}; extra={observed - expected}"
                )
        expected_bindings = {
            item["id"]: item["symbol"] for item in [*case["blocks"], *case["ports"]]
        }
        if set(doc.bindings) != set(expected_bindings):
            errors.append("Every block and port must have its own explicit code link")
        for identity, symbol in expected_bindings.items():
            binding = doc.bindings.get(identity, {})
            if binding.get("symbol") != symbol or binding.get("status") != "resolved":
                errors.append(
                    f"Unresolved or incorrect code binding: {identity} -> {symbol}"
                )
        return {
            "case": case["id"],
            "passed": not errors,
            "errors": errors,
            "blocks": len(doc.blocks),
            "ports": len(doc.ports),
            "connections": len(doc.connections),
        }

    def check(self, cases):
        graph = self.prepare()
        results = [self.verify(case, self.document(case, graph)) for case in cases]
        report = {
            "passed": all(r["passed"] for r in results),
            "checks": results,
            "meaning": "Presentation topology and navigation checks, not architecture conformance.",
        }
        self.write_json("reports/check.json", report)
        return report

    def gallery_html(self, cases, *, exported=False):
        cards = []
        for case in cases:
            identity = case["id"]
            href = identity + ".html" if exported else "/examples/" + identity
            cards.append(
                f'<section><h2><a href="{href}">{html.escape(case["title"])}</a></h2>'
                f'<p>{html.escape(case["description"])}</p>'
                f"<p><code>./run.sh serve {identity} --open</code> · "
                f'{len(case["blocks"])} blocks / {len(case["ports"])} ports / '
                f'{len(case["connections"])} connections · <a href="{href}">Open full diagram</a></p>'
                f'<iframe loading="lazy" title="{html.escape(case["title"])}" src="{href}"></iframe></section>'
            )
        navigation = (
            "Offline diagrams. Code links are disabled unless exported with --code-url pointing to this gallery's live source viewer."
            if exported
            else "Click any block title or boundary pin to open its pinned source declaration in a new tab. Refresh a diagram after editing its D2."
        )
        return (
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Hx D2 repository examples</title>'
            "<style>body{margin:24px auto;max-width:1500px;padding:0 20px;font:16px system-ui;color:#192b40;background:#f6f8fc}"
            "section{margin:32px 0;background:white;border:1px solid #c6d0dd;padding:18px;border-radius:8px}"
            "iframe{width:100%;height:560px;border:1px solid #c6d0dd}a{color:#185ba4}code{font-size:14px}</style>"
            "<h1>Hx D2 repository examples</h1><p>Authored architecture sketches of Codex, FFmpeg and Hx. "
            "Links use selected real declarations; arrows do not assert extracted dataflow or behavioral validation.</p>"
            f"<p>{html.escape(navigation)}</p><p>Blue pins are inputs; orange pins are outputs. "
            "Dashed arrows expose nested ports. Scroll to zoom, drag empty space to pan, and use fit to reset.</p>"
            + "".join(cards)
            + "</html>"
        )

    def app(self, cases, graph):
        from fastapi import HTTPException, Request
        from fastapi.responses import HTMLResponse
        from hx.architecture.presentation import build_html
        from hx.serve.app import create_app

        app = create_app(str(graph), allow_extract=False)
        selected = {c["id"]: c for c in cases}

        @app.get("/examples", response_class=HTMLResponse)
        def gallery():
            return self.gallery_html(cases)

        # Request must be available to FastAPI when resolving postponed annotations.
        def diagram(identity: str, request: Request):
            if identity not in selected:
                raise HTTPException(404, "Unknown example; see /examples")
            try:
                doc = self.document(selected[identity], graph)
                return build_html(doc, code_url=str(request.base_url))
            except (OSError, ValueError) as exc:
                raise HTTPException(400, str(exc)) from exc

        # FastAPI evaluates the local annotation above against module globals.
        diagram.__annotations__["request"] = Request
        app.get("/examples/{identity}", response_class=HTMLResponse)(diagram)
        return app

    def export(self, cases, code_url=None):
        from hx.architecture.presentation import build_html
        from hx.fsutil import atomic_write

        graph = self.prepare()
        for case in cases:
            doc = self.document(case, graph)
            check = self.verify(case, doc)
            if not check["passed"]:
                raise ExampleError("; ".join(check["errors"]))
            path = self.output("exports/" + case["id"] + ".html")
            atomic_write(str(path), build_html(doc, code_url=code_url))
        index = self.output("exports/index.html")
        atomic_write(str(index), self.gallery_html(cases, exported=True))
        return index


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--d2-bridge", help="explicit bridge executable (or use HX_TOOL_D2_BRIDGE)"
    )
    sub = p.add_subparsers(dest="command", required=True)
    setup = sub.add_parser(
        "setup", help="explicitly build the bridge; bootstrap user-local Go if needed"
    )
    setup.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="arguments after -- go to setup_d2_bridge.sh",
    )
    sub.add_parser("list", help="list cases and their presentation features")
    inspect = sub.add_parser(
        "inspect", help="interpret a case and verify topology and links"
    )
    inspect.add_argument("case", nargs="?", default="all")
    inspect.add_argument("--json", action="store_true")
    for name in ("serve", "gallery"):
        s = sub.add_parser(
            name, help="foreground local preview with working code links"
        )
        if name == "serve":
            s.add_argument("case")
        s.add_argument("--port", type=int, default=8766)
        s.add_argument("--open", action="store_true")
    export = sub.add_parser(
        "export", help="write ignored standalone HTML diagrams and gallery"
    )
    export.add_argument("case", nargs="?", default="all")
    export.add_argument(
        "--code-url",
        help="explicit live gallery viewer URL, e.g. http://127.0.0.1:8766/",
    )
    check = sub.add_parser(
        "check", help="verify sources, authored expectations and code bindings"
    )
    check.add_argument("case", nargs="?", default="all")
    check.add_argument(
        "--browser",
        action="store_true",
        help="also measure layouts and click every code link (Playwright)",
    )
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "setup":
            extra = args.args[1:] if args.args[:1] == ["--"] else args.args
            return subprocess.call(
                ["bash", str(REPO / "dev/scripts/setup_d2_bridge.sh"), *extra],
                env={**os.environ, "PYTHON": sys.executable},
            )
        examples = Examples(bridge=args.d2_bridge)
        if args.command == "list":
            for case in examples.cases.values():
                print(f"{case['id']:20} {case['description']}")
            return 0
        cases = examples.selected(getattr(args, "case", "all"))
        if args.command in {"inspect", "check"}:
            report = examples.check(cases)
            if args.command == "inspect" and args.json:
                graph = examples.generated / ".hx/graph.json"
                print(
                    json.dumps(
                        [examples.document(c, graph).to_dict() for c in cases], indent=2
                    )
                )
            else:
                for result in report["checks"]:
                    print(
                        f"{'PASS' if result['passed'] else 'FAIL'} {result['case']}: "
                        f"{result['blocks']} blocks, {result['ports']} ports, {result['connections']} connections"
                    )
                    for error in result["errors"]:
                        print("  " + error)
            if not report["passed"]:
                return 1
            if args.command == "check" and args.browser:
                from browser_check import check_browser

                try:
                    browser_report = check_browser(examples, cases)
                except Exception as exc:
                    raise ExampleError(f"Browser check failed: {exc}") from exc
                print(
                    f"Browser {'PASS' if browser_report['passed'] else 'FAIL'}: "
                    f"{len(browser_report['runs'])} layout/zoom combinations, "
                    f"{2 * len(browser_report['runs'])} measured views, "
                    f"{sum(len(r['clicks']) for r in browser_report['runs'])} code clicks"
                )
                print(examples.generated / "reports/browser.json")
                return 0 if browser_report["passed"] else 1
            print(examples.generated / "reports/check.json", file=sys.stderr)
            return 0
        if args.command == "export":
            print(examples.export(cases, args.code_url))
            return 0
        import uvicorn
        from threading import Timer

        if not 1 <= args.port <= 65535:
            raise ExampleError("--port must be between 1 and 65535")
        graph = examples.prepare()
        for case in cases:
            result = examples.verify(case, examples.document(case, graph))
            if not result["passed"]:
                raise ExampleError("; ".join(result["errors"]))
        app = examples.app(cases, graph)
        url = f"http://127.0.0.1:{args.port}/examples"
        if args.command == "serve":
            url += "/" + cases[0]["id"]
        print(
            f"Preview: {url}\nCode viewer: http://127.0.0.1:{args.port}/\nStop with Ctrl+C",
            flush=True,
        )
        timer = Timer(1, webbrowser.open, args=(url,)) if args.open else None
        if timer:
            timer.daemon = True
            timer.start()
        try:
            uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
        finally:
            if timer:
                timer.cancel()
        return 0
    except (OSError, ValueError, ImportError) as exc:
        print(
            f"Example error: {exc}\nSee {HERE / 'README.md'} for prerequisites and recovery.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
