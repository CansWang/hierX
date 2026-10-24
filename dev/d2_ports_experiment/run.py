#!/usr/bin/env python3
"""Measure stock D2 boundary ports. Exit 0 qualified, 1 none qualified, 2 setup error."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import partial
from datetime import datetime, timezone
import hashlib
import html
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import platform
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import urlencode

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from dev.d2_ports_experiment.geometry import analyze  # noqa: E402
from dev.d2_ports_experiment.model import fixture_cases  # noqa: E402

HERE = Path(__file__).resolve().parent
VERSION = "v0.9.0"
PROFILES = [
    ("elk", "default", []),
    ("dagre", "default", []),
    ("tala", "default", []),
    ("elk", "zero-padding", ["--elk-padding", "[top=28,left=0,bottom=28,right=0]"]),
]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def run_command(command, log, *, cwd=None, env=None, timeout=60):
    start = time.monotonic()
    try:
        result = subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
        info = {
            "command": list(map(str, command)),
            "exit": result.returncode,
            "seconds": time.monotonic() - start,
        }
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        info = {
            "command": list(map(str, command)),
            "exit": None,
            "seconds": time.monotonic() - start,
            "error": "timeout",
        }
        log.write_text(str(exc), encoding="utf-8")
    return info


def code_urls(case, graph, base):
    """Resolve explicit code identities, without architecture ownership rules."""
    urls = {}
    errors = []
    for item in [*case.blocks, *case.ports]:
        node = graph["nodes"].get(item.code.symbol)
        if not node:
            errors.append(
                {
                    "code": "unresolved-code-link",
                    "subject": item.id,
                    "symbol": item.code.symbol,
                }
            )
            continue
        if item.code.member.startswith("parameter:"):
            name = item.code.member.split(":", 1)[1]
            if name not in {p["name"] for p in node.get("params", [])}:
                errors.append(
                    {
                        "code": "unresolved-code-member",
                        "subject": item.id,
                        "member": item.code.member,
                    }
                )
                continue
        # Return positions are authored fixture descriptors, not inferred dataflow
        # or token-level links. Both return ports navigate to the owning function.
        urls[item.id] = (
            base + "/#" + urlencode({"kind": "node", "sel": item.code.symbol})
        )
    return urls, errors


@contextmanager
def servers(output, graph_path, source):
    import uvicorn
    from hx.serve.app import create_app

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    static = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(Quiet, directory=str(output))
    )
    static_thread = threading.Thread(target=static.serve_forever, daemon=True)
    static_thread.start()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    app = create_app(
        str(graph_path), root=str(source), allow_extract=False, poll_interval=0.1
    )
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError("Hx viewer failed to start")
            time.sleep(0.025)
        if not server.started:
            raise RuntimeError("Hx viewer startup timed out")
        yield f"http://127.0.0.1:{static.server_address[1]}", f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=5)
        sock.close()
        static.shutdown()
        static.server_close()
        static_thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("Hx viewer did not shut down")


def prepare_inputs(output, urls):
    inputs = output / "inputs"
    shutil.copytree(HERE / "fixtures", inputs, ignore=shutil.ignore_patterns("rust"))
    # Shared worker definitions are independently instantiated but deliberately
    # link to the same source function. All substitutions are link values only.
    for suffix in ("", "in_sample", "in_valid", "out_sample", "out_valid"):
        key = "worker" + ("." + suffix if suffix else "")
        urls[key] = urls["pipeline.first" + ("." + suffix if suffix else "")]
    for file in inputs.glob("*.d2"):
        text = file.read_text()

        def replace(match):
            key = match.group(1)
            if key not in urls:
                raise ValueError(f"Unknown fixture code placeholder {key}")
            return urls[key]

        file.write_text(
            re.sub(r"__HX_CODE_([a-z_.]+)__", replace, text), encoding="utf-8"
        )
    return inputs


def inspect_svg(page, svg_url, zoom):
    page.goto(svg_url, wait_until="load")
    page.evaluate("(zoom)=>{document.documentElement.style.zoom=String(zoom);}", zoom)
    measured = page.evaluate((HERE / "measure.js").read_text())
    # Standard link-target metadata makes code navigation open a separate tab.
    # The D2-produced shapes, routes and labels are never changed.
    page.evaluate(
        "document.querySelectorAll('a').forEach(a=>a.setAttribute('target','_blank'))"
    )
    return measured


def check_navigation(context, page, case, urls):
    results = []
    for item in [*case.blocks, *case.ports]:
        result = {
            "id": item.id,
            "symbol": item.code.symbol,
            "member": item.code.member,
            "passed": False,
        }
        target = None
        try:
            group = page.locator(f'g[data-hx-id="{item.id}"]')
            clickable = (
                group.locator("text").first
                if item in case.blocks
                else group.locator("ellipse,circle,rect,path").first
            )
            page.bring_to_front()
            clickable.scroll_into_view_if_needed(timeout=2000)
            visible = clickable.evaluate(
                """el=>{
                const b=el.getBoundingClientRect();
                const hit=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);
                return {clear:hit===el || el.contains(hit),obstruction:hit?.outerHTML.slice(0,250)};
            }"""
            )
            if not visible["clear"]:
                raise AssertionError(
                    "Glyph/title centre is obscured: " + str(visible["obstruction"])
                )
            with context.expect_page(timeout=4000) as pending:
                clickable.click(timeout=4000)
            target = pending.value
            target.wait_for_load_state("domcontentloaded")
            target.wait_for_function(
                '(id)=>document.querySelector("#tree .row.sel")?.title===id',
                arg=item.code.symbol,
                timeout=8000,
            )
            target.locator("#source-holder .src .ln").first.wait_for(timeout=8000)
            signature = target.locator("#detail .sig").inner_text()
            source = target.locator("#source-holder").inner_text()
            function = item.code.symbol.split("::")[-1]
            if function not in signature or f"fn {function}(" not in source:
                raise AssertionError("Wrong function/source content")
            if (
                item.code.member.startswith("parameter:")
                and item.code.member.split(":", 1)[1] not in signature
            ):
                raise AssertionError("Bound parameter is not visible")
            if item.code.member.startswith("return:") and "->" not in signature:
                raise AssertionError("Return signature is not visible")
            result.update(passed=True, signature=signature, url=target.url)
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            if target:
                target.close()
        results.append(result)
    return results


def measure_render(browser, static_base, output, svg, case, urls, screenshot):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    result = []
    try:
        for zoom in (1, 1.5):
            measured = inspect_svg(
                page, static_base + "/" + svg.relative_to(output).as_posix(), zoom
            )
            stem = svg.with_suffix("")
            suffix = f"-zoom-{int(zoom*100)}"
            if screenshot:
                # A viewport capture is bounded even for a large nested deck.
                # The original SVG remains available for full inspection.
                page.bring_to_front()
                page.screenshot(path=str(stem) + suffix + ".png", timeout=10000)
            analysis = analyze(case, measured, urls)
            navigation = check_navigation(context, page, case, urls)
            analysis["navigation"] = navigation
            analysis["passed"] = analysis["passed"] and all(
                n["passed"] for n in navigation
            )
            write_json(Path(str(stem) + suffix + ".geometry.json"), measured)
            write_json(Path(str(stem) + suffix + ".checks.json"), analysis)
            result.append({"zoom": zoom, **analysis})
    finally:
        context.close()
    return result


def gallery(output, report):
    rows = []
    for item in report.get("renders", []):
        if not item.get("svg"):
            continue
        status = "PASS" if item.get("passed") else "FAIL"
        errors = sorted(
            {e["code"] for check in item.get("checks", []) for e in check["errors"]}
        )
        navigation = sum(
            n["passed"]
            for check in item.get("checks", [])
            for n in check.get("navigation", [])
        )
        rows.append(
            f'<section><h2>{html.escape(item["engine"]+" / "+item["profile"]+" / "+item["case"])} — {status}</h2>'
            f'<p>{html.escape(", ".join(errors))}; successful code clicks: {navigation}</p>'
            f'<p><a href="{html.escape(item["svg"])}">Open original SVG</a></p>'
            f'<object type="image/svg+xml" data="{html.escape(item["svg"])}"></object></section>'
        )
    controls = "".join(
        f'<p>{html.escape(c["engine"])}: <a href="{html.escape(c["svg"])}">table-row comparison</a> '
        "(excluded from boundary-pin qualification)</p>"
        for c in report.get("controls", [])
        if c.get("svg")
    )
    output.joinpath("gallery.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>D2 boundary-port experiment</title>'
        "<style>body{font:16px sans-serif;margin:24px}object{width:100%;height:650px;border:1px solid #bbb}section{margin:35px 0}</style>"
        "<h1>D2 boundary-port experiment</h1><p>Original D2 geometry. Table anchors do not qualify as visible pins. "
        "Code links require the recorded Hx server; see report.json.</p>"
        + controls
        + "".join(rows),
        encoding="utf-8",
    )
    lines = [
        "# D2 boundary-port feasibility result",
        "",
        f'Qualified profiles: {", ".join(report.get("qualified",[])) or "none"}',
        "",
        "| Engine/profile | Case | Result | Pin distance range (SVG units) | Code clicks | Diagnostics |",
        "|---|---|---|---|---|---|",
    ]
    for item in report.get("renders", []):
        checks = item.get("checks", [])
        pins = [
            p["border_distance"] for c in checks for p in c["metrics"]["pins"].values()
        ]
        clicks = [n for c in checks for n in c["navigation"]]
        diagnostics = sorted({e["code"] for c in checks for e in c["errors"]})
        distances = f"{min(pins):.2f}–{max(pins):.2f}" if pins else "unavailable"
        lines.append(
            f'| {item["engine"]}/{item["profile"]} | {item["case"]} | {"pass" if item.get("passed") else "fail"} '
            f'| {distances} | {sum(n["passed"] for n in clicks)}/{len(clicks)} | {", ".join(diagnostics)} |'
        )
    lines += [
        "",
        "Recommendation: "
        + (
            "Consider a separate integration phase for the qualified profile."
            if report.get("qualified")
            else "Do not replace TOML with this D2 profile. Reconsider D2 as an authoring frontend for a port-aware renderer, or evaluate another representation."
        ),
        "",
        "These results concern the tested version, profiles and fixtures; they do not establish impossibility for every D2 encoding.",
        "",
        "No Hx geometry adapter or contractual checking was used.",
        "All results include 100% and 150% browser zoom. Click counts include both views. Native link icons may obscure a pin even when its href is correct.",
        "Repetition runs are required only after a profile passes every case once. Table-row controls are retained separately and cannot qualify.",
    ]
    output.joinpath("findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def experiment(d2, output):
    from hx.api import extract
    from playwright.sync_api import sync_playwright

    report = {
        "experiment": "d2-boundary-ports/1",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "d2_version": VERSION,
        "renders": [],
        "qualified": [],
        "geometry_adapter": False,
        "pin_tolerance_svg_units": 2,
        "code_navigation": "owning function, signature and source; no token-level highlighting",
        "harness_sha256": {
            p.relative_to(HERE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in HERE.rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and p.suffix not in {".pyc", ".png"}
        },
    }
    version = run_command([str(d2), "--version"], output / "version.log")
    if version["exit"] != 0 or (output / "version.log").read_text().strip() != VERSION:
        raise ValueError(f"Expected D2 {VERSION}; see version.log")
    report["d2_binary_sha256"] = hashlib.sha256(d2.read_bytes()).hexdigest()
    report["engine_inventory"] = run_command(
        [str(d2), "layout"], output / "engines.log"
    )
    inventory = (output / "engines.log").read_text()
    if report["engine_inventory"]["exit"] != 0:
        raise ValueError("Could not enumerate D2 engines")
    cases = fixture_cases()
    missing = [
        engine
        for engine in {p[0] for p in PROFILES}
        if not re.search(r"^" + re.escape(engine) + r"\s", inventory, re.M)
    ]
    if missing:
        raise ValueError(
            "Required D2 engines unavailable: " + ", ".join(sorted(missing))
        )
    write_json(output / "model.json", [case.to_dict() for case in cases])
    source = output / "source/rust"
    source.parent.mkdir()
    shutil.copytree(HERE / "fixtures/rust", source)
    with tempfile.TemporaryDirectory(prefix="hx-d2-build-") as build:
        old_env = {key: os.environ.get(key) for key in ("PATH", "CARGO_TARGET_DIR")}
        os.environ["PATH"] = (
            str(Path.home() / ".cargo/bin") + os.pathsep + os.environ.get("PATH", "")
        )
        os.environ["CARGO_TARGET_DIR"] = build
        try:
            for name in ("cargo", "rustc", "rust-analyzer"):
                info = run_command(
                    [name, "--version"], output / (name + "-version.log")
                )
                if info["exit"] != 0:
                    raise ValueError(f"{name} unavailable")
            cargo = run_command(
                ["cargo", "test", "--locked"],
                output / "cargo-test.log",
                cwd=source,
                timeout=120,
            )
            if cargo["exit"] != 0:
                raise ValueError("Rust fixture tests failed")
            report["cargo_test"] = cargo
            graph = extract("src/lib.rs:run", root=str(source), depth=None)
            graph_path = output / "graph.json"
            graph.save(str(graph_path))
            graph = graph.to_dict()
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    with (
        servers(output, graph_path, source) as (static_base, viewer_base),
        sync_playwright() as playwright,
    ):
        report["viewer_url"] = viewer_base
        report["reopen_code_links_command"] = (
            f'hx serve {graph_path} --root {source} --port {viewer_base.rsplit(":",1)[1]} --no-extract'
        )
        browser = playwright.chromium.launch(headless=True)
        report["chromium"] = browser.version
        try:
            urls = {}
            binding_errors = []
            for case in cases:
                resolved, errors = code_urls(case, graph, viewer_base)
                urls.update(resolved)
                binding_errors += errors
            report["binding_errors"] = binding_errors
            if binding_errors:
                raise ValueError("Unresolved fixture bindings")
            inputs = prepare_inputs(output, dict(urls))
            report["input_sha256"] = {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in inputs.glob("*.d2")
            }
            # Native row anchors are retained as a visual comparison only.
            # They cannot qualify: they contain no separate boundary pin glyphs.
            for engine in sorted({p[0] for p in PROFILES}):
                directory = output / "controls" / engine
                directory.mkdir(parents=True)
                svg = directory / "rows.svg"
                info = run_command(
                    [
                        str(d2),
                        "--layout=" + engine,
                        "--theme=0",
                        "--pad=30",
                        str(inputs / "rows-control.d2"),
                        str(svg),
                    ],
                    directory / "compiler.log",
                )
                report.setdefault("controls", []).append(
                    {
                        "engine": engine,
                        "compiler": info,
                        "svg": (
                            svg.relative_to(output).as_posix() if svg.exists() else None
                        ),
                        "qualifies": False,
                        "reason": "Row anchors do not supply dedicated visible boundary pins",
                    }
                )
            for engine, profile, flags in PROFILES:
                profile_results = []
                run_command(
                    [str(d2), "layout", engine], output / (engine + "-help.log")
                )
                for case in cases:
                    directory = output / "renders" / engine / profile / case.name
                    directory.mkdir(parents=True)
                    svg = directory / "render.svg"
                    item = {
                        "engine": engine,
                        "profile": profile,
                        "case": case.name,
                        "passed": False,
                    }
                    command = [
                        str(d2),
                        "--layout=" + engine,
                        "--theme=0",
                        "--pad=30",
                        *flags,
                        str(inputs / (case.name + ".d2")),
                        str(svg),
                    ]
                    item["compiler"] = run_command(command, directory / "compiler.log")
                    if item["compiler"]["exit"] == 0 and svg.exists():
                        item["svg"] = svg.relative_to(output).as_posix()
                        item["checks"] = measure_render(
                            browser, static_base, output, svg, case, urls, True
                        )
                        item["passed"] = all(
                            check["passed"] for check in item["checks"]
                        )
                    profile_results.append(item)
                    report["renders"].append(item)
                    print(
                        f'{engine}/{profile}/{case.name}: {"PASS" if item["passed"] else "FAIL"}',
                        flush=True,
                    )
                    write_json(output / "report.json", report)
                # Repetition is a reliability gate, not repeated testing of an
                # already failed layout. All cases first need to pass once.
                if all(item["passed"] for item in profile_results):
                    stable = True
                    for repeat in (2, 3):
                        for case, original in zip(cases, profile_results):
                            svg = output / original["svg"]
                            repeated = svg.with_name(f"repeat-{repeat}.svg")
                            command = [
                                str(d2),
                                "--layout=" + engine,
                                "--theme=0",
                                "--pad=30",
                                *flags,
                                str(inputs / (case.name + ".d2")),
                                str(repeated),
                            ]
                            info = run_command(command, repeated.with_suffix(".log"))
                            checks = (
                                measure_render(
                                    browser,
                                    static_base,
                                    output,
                                    repeated,
                                    case,
                                    urls,
                                    False,
                                )
                                if info["exit"] == 0
                                else []
                            )
                            passed = bool(checks) and all(
                                c["passed"]
                                and c["identities"]
                                == original["checks"][0]["identities"]
                                for c in checks
                            )
                            stable &= passed
                            report.setdefault("repeats", []).append(
                                {
                                    "engine": engine,
                                    "profile": profile,
                                    "case": case.name,
                                    "repeat": repeat,
                                    "compiler": info,
                                    "passed": passed,
                                }
                            )
                    if stable:
                        report["qualified"].append(engine + "/" + profile)
        finally:
            browser.close()
    for name in ("target", ".hx"):
        shutil.rmtree(source / name, ignore_errors=True)
    report["test_servers_closed"] = True
    report["recommendation"] = (
        "consider-integration" if report["qualified"] else "reconsider-d2-role"
    )
    write_json(output / "report.json", report)
    gallery(output, report)
    return 0 if report["qualified"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--d2", required=True, type=Path, help="Private, unmodified D2 v0.9.0 binary"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="New or empty evidence directory"
    )
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("output must be a new or empty directory")
    output.mkdir(parents=True, exist_ok=True)
    try:
        return experiment(args.d2.resolve(), output)
    except Exception as exc:
        write_json(
            output / "setup-error.json",
            {"error": type(exc).__name__, "message": str(exc)},
        )
        (output / "setup-error.log").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        print(f"Experiment setup/instrumentation failed: {exc}", file=sys.stderr)
        return 2
    finally:
        for name in ("target", ".hx"):
            shutil.rmtree(output / "source/rust" / name, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
