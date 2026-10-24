"""Optional real-browser acceptance for the repository examples."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import socket
import threading
import time


@contextmanager
def running(app):
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError("Example gallery failed to start")
            time.sleep(0.025)
        if not server.started:
            raise RuntimeError("Example gallery startup timed out")
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        if thread.is_alive():
            raise RuntimeError("Example gallery did not stop")


def oracle(case):
    from dev.d2_ports_experiment.model import Block, Case, CodeRef, Connection, Port

    return Case(
        case["id"],
        [Block(b["id"], b["parent"], CodeRef(b["symbol"])) for b in case["blocks"]],
        [
            Port(p["id"], p["block"], p["direction"], CodeRef(p["symbol"]))
            for p in case["ports"]
        ],
        [
            Connection(e["source"], e["target"], e["label"], e["kind"])
            for e in case["connections"]
        ],
    )


def click_links(context, page, case, nodes, source_root):
    """Click the actual titles/pins and compare rendered signatures and source text."""
    clicks = []
    for item in [*case["blocks"], *case["ports"]]:
        result = {"id": item["id"], "symbol": item["symbol"], "passed": False}
        target = None
        try:
            group = page.locator(f'g[data-hx-id="{item["id"]}"]')
            glyph = group.locator("text" if item in case["blocks"] else "circle").first
            page.bring_to_front()
            glyph.scroll_into_view_if_needed(timeout=4000)
            visible = glyph.evaluate(
                """el=>{
                const b=el.getBoundingClientRect(), hit=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);
                return hit===el || el.contains(hit);
            }"""
            )
            if not visible:
                raise AssertionError("Clickable title/pin is obscured")
            with context.expect_page(timeout=5000) as pending:
                glyph.click(timeout=4000)
            target = pending.value
            target.wait_for_load_state("domcontentloaded")
            # The declaration catalog has no invented hierarchy edges; most
            # declarations are therefore absent from the default entry tree.
            target.wait_for_function(
                "(id)=>window.HX_DEBUG?.state().sel?.id===id",
                arg=item["symbol"],
                timeout=10000,
            )
            target.locator("#source-holder .src .ln").first.wait_for(timeout=10000)
            node = nodes[item["symbol"]]
            signature = target.locator("#detail .sig").inner_text()
            if " ".join(signature.split()) != " ".join(node["signature"].split()):
                raise AssertionError("Wrong rendered declaration signature")
            if (
                f"{node['loc']['file']}:{node['loc']['line']}"
                not in target.locator("#detail .meta").inner_text()
            ):
                raise AssertionError("Wrong source file or declaration line")
            lines = target.locator("#source-holder .src .ln pre").all_text_contents()
            first = node["loc"]["line"] - 1
            end = min(node["loc"].get("end_line") or first + 31, first + 400)
            expected = (
                (source_root / node["loc"]["file"])
                .read_text(encoding="utf-8")
                .splitlines()[first:end]
            )
            if [line.rstrip() for line in lines] != [
                line.rstrip() for line in expected
            ]:
                raise AssertionError(
                    "Rendered source differs from pinned declaration text"
                )
            result.update(passed=True, file=node["loc"]["file"], line=first + 1)
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            if target:
                target.close()
        clicks.append(result)
    return clicks


def check_browser(examples, cases, *, repeats=3, zooms=(1, 1.5)):
    """Measure the production SVG, then genuinely navigate from every block/port."""
    from dev.d2_ports_experiment.geometry import analyze
    from hx.architecture.presentation import payload
    from hx.tools import find_tool
    from playwright.sync_api import sync_playwright

    repo = Path(__file__).resolve().parents[2]
    measure = (repo / "dev/d2_integration_experiment/measure.js").read_text()
    graph = examples.prepare()
    nodes = json.loads(graph.read_text())["nodes"]
    bridge = Path(find_tool("d2_bridge", examples.bridge) or "hx-d2-bridge")
    inputs = [
        examples.base / "examples.json",
        examples.base / "navigation.json",
        examples.base / "sources/manifest.json",
        *sorted((examples.base / "cases").rglob("*.d2")),
    ]
    report = {
        "passed": False,
        "complete": False,
        "runs": [],
        "errors": [],
        "repeats": repeats,
        "zooms": list(zooms),
        "input_sha256": {
            str(p.relative_to(examples.base)): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in inputs
        },
        "bridge_sha256": hashlib.sha256(bridge.read_bytes()).hexdigest(),
        "elk_sha256": hashlib.sha256(
            (repo / "hx/viewer/vendor/elk.bundled.js").read_bytes()
        ).hexdigest(),
        "renderer_sha256": hashlib.sha256(
            (repo / "hx/architecture/diagram.js").read_bytes()
        ).hexdigest(),
    }

    def save():
        examples.write_json("reports/browser.json", report)

    save()
    with sync_playwright() as pw, running(examples.app(cases, graph)) as base:
        browser = None
        report["viewer_url_at_capture"] = base
        try:
            browser = pw.chromium.launch(headless=True)
            report["chromium"] = browser.version
            for repeat in range(repeats):
                for case in cases:
                    context = browser.new_context(
                        viewport={"width": 1800, "height": 1100}
                    )
                    page = context.new_page()
                    page_errors = []
                    page.on("pageerror", lambda e: page_errors.append(str(e)))
                    try:
                        page.goto(base + "/examples/" + case["id"])
                        page.wait_for_function(
                            "window.HX_ARCH_READY || window.HX_ARCH_ERROR",
                            timeout=30000,
                        )
                        error = page.evaluate("window.HX_ARCH_ERROR")
                        if error:
                            raise AssertionError(error)
                        doc = examples.document(case, graph)
                        urls = payload(doc, base + "/")["code_urls"]
                        # Use the real SVG scale so genuine clicks hit even large diagrams.
                        page.locator("svg").evaluate(
                            "e=>{const v=e.viewBox.baseVal;e.style.width=v.width+'px';e.style.height=v.height+'px'}"
                        )
                        page.locator("#canvas").evaluate("e=>e.style.overflow='auto'")
                        if repeat == 0:
                            examples.output(f"browser/{case['id']}.svg").write_text(
                                page.locator("svg").evaluate("e=>e.outerHTML")
                            )
                            examples.write_json(
                                f"browser/{case['id']}-layout.json",
                                page.evaluate("window.HX_ARCH_LAYOUT"),
                            )
                        for zoom in zooms:
                            page.evaluate(
                                "z=>document.documentElement.style.zoom=String(z)", zoom
                            )
                            page.locator("svg").evaluate(
                                "e=>{e.style.width='100%';e.style.height='100%'}"
                            )
                            page.locator("#fit").click()
                            fit_geometry = analyze(
                                oracle(case), page.evaluate(measure), urls
                            )
                            if repeat == 0 or not fit_geometry["passed"]:
                                page.screenshot(
                                    path=str(
                                        examples.output(
                                            f"browser/{case['id']}-{repeat}-{zoom}.png"
                                        )
                                    )
                                )
                            page.locator("svg").evaluate(
                                "e=>{const v=e.viewBox.baseVal;e.style.width=v.width+'px';e.style.height=v.height+'px'}"
                            )
                            page.locator("#canvas").evaluate(
                                "e=>{e.scrollLeft=0;e.scrollTop=0}"
                            )
                            measured = page.evaluate(measure)
                            geometry = analyze(oracle(case), measured, urls)
                            clicks = (
                                click_links(
                                    context,
                                    page,
                                    case,
                                    nodes,
                                    examples.base / "sources",
                                )
                                if geometry["passed"] and fit_geometry["passed"]
                                else []
                            )
                            result = {
                                "case": case["id"],
                                "repeat": repeat,
                                "zoom": zoom,
                                "geometry": geometry,
                                "fit_geometry": fit_geometry,
                                "clicks": clicks,
                                "page_errors": list(page_errors),
                                "passed": geometry["passed"]
                                and fit_geometry["passed"]
                                and not page_errors
                                and len(clicks)
                                == len(case["blocks"]) + len(case["ports"])
                                and all(c["passed"] for c in clicks),
                            }
                            report["runs"].append(result)
                            save()
                            print(
                                f"  {'PASS' if result['passed'] else 'FAIL'} {case['id']} layout {repeat + 1}/{repeats} zoom {zoom}",
                                flush=True,
                            )
                            if not result["passed"]:
                                return report
                    finally:
                        context.close()
        except Exception as exc:
            report["errors"].append(str(exc))
            save()
            raise
        finally:
            if browser:
                browser.close()
    report["complete"] = len(report["runs"]) == repeats * len(zooms) * len(cases)
    report["measured_views"] = 2 * len(report["runs"])
    report["passed"] = (
        report["complete"]
        and bool(report["runs"])
        and all(r["passed"] for r in report["runs"])
    )
    save()
    return report
