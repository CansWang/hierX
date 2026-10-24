"""Independent presentation gate for upstream D2 -> Hx -> direct ELK.

The original stock-D2 experiment and its authored oracle remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright
from dev.d2_ports_experiment.geometry import analyze
from dev.d2_ports_experiment.model import Block, Case, CodeRef, Connection, Port, fixture_cases
from dev.d2_ports_experiment.run import check_navigation, servers
from hx.api import extract
from hx.architecture import load_architecture
from hx.architecture.presentation import build_html, payload


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def cases():
    handshake = Case("handshake", [Block("source", None, CodeRef("rs:src/lib.rs::produce")), Block("sink", None, CodeRef("rs:src/lib.rs::consume"))],
                     [Port("source.ready", "source", "in", CodeRef("rs:src/lib.rs::produce")),
                      Port("source.data", "source", "out", CodeRef("rs:src/lib.rs::produce")),
                      Port("sink.data", "sink", "in", CodeRef("rs:src/lib.rs::consume")),
                      Port("sink.ready", "sink", "out", CodeRef("rs:src/lib.rs::consume"))],
                     [Connection("source.data", "sink.data", "data"), Connection("sink.ready", "source.ready", "ready")])
    return [*fixture_cases(), handshake]


def run(bridge, elk, output, selected=None):
    output.mkdir(parents=True, exist_ok=False)
    report = {"experiment": "hx-d2-elk/1", "passed": False, "runs": [],
              "d2_bridge_sha256": hashlib.sha256(bridge.read_bytes()).hexdigest(),
              "elk_sha256": hashlib.sha256(elk.read_bytes()).hexdigest()}
    write(output / "report.json", report)
    source = output / "source/rust"
    source.parent.mkdir()
    shutil.copytree(ROOT / "dev/d2_ports_experiment/fixtures/rust", source)
    inputs = output / "inputs"
    shutil.copytree(ROOT / "tests/fixtures/architecture", inputs)
    with tempfile.TemporaryDirectory(prefix="hx-arch-rust-") as target:
        previous = {k: os.environ.get(k) for k in ("PATH", "CARGO_TARGET_DIR")}
        os.environ["PATH"] = str(Path.home() / ".cargo/bin") + os.pathsep + os.environ["PATH"]
        os.environ["CARGO_TARGET_DIR"] = target
        try:
            cargo = subprocess.run(["cargo", "test", "--locked"], cwd=source, text=True, capture_output=True, timeout=120)
            (output / "cargo-test.log").write_text(cargo.stdout + cargo.stderr)
            assert cargo.returncode == 0, "Rust fixture tests failed"
            graph = extract("src/lib.rs:run", root=str(source), depth=None)
            graph.save(str(output / "graph.json"))
        finally:
            for k, v in previous.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v
    selected_cases = [c for c in cases() if not selected or c.name in selected]
    with servers(output, output / "graph.json", source) as (static, viewer), sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        report["chromium"] = browser.version
        report["viewer_url"] = viewer
        report["reopen_code_links_command"] = f'hx serve {output / "graph.json"} --root {source} --port {viewer.rsplit(":", 1)[1]} --no-extract'
        for repeat in range(3):
            for case in selected_cases:
                doc = load_architecture(str(inputs / (case.name + ".d2")), graph=str(output / "graph.json"), bridge=str(bridge))
                assert doc.valid, doc.diagnostics
                assert all(b["status"] == "resolved" for b in doc.bindings.values()), doc.diagnostics
                data = payload(doc, viewer + "/")
                name = f"{case.name}-{repeat}"
                (output / (name + ".html")).write_text(build_html(doc, code_url=viewer+"/", _elk_source=elk.read_text()))
                write(output / (name + "-model.json"), data)
                context = browser.new_context(viewport={"width": 1800, "height": 1100})
                page = context.new_page()
                page.goto(static + "/" + name + ".html")
                page.wait_for_function("window.HX_ARCH_READY || window.HX_ARCH_ERROR", timeout=30000)
                assert not page.evaluate("window.HX_ARCH_ERROR"), page.evaluate("window.HX_ARCH_ERROR")
                write(output / (name + "-layout.json"), page.evaluate("window.HX_ARCH_LAYOUT"))
                (output / (name + ".svg")).write_text(page.locator("svg").evaluate("e=>e.outerHTML"))
                for zoom in (1, 1.5):
                    page.evaluate("z=>document.documentElement.style.zoom=String(z)", zoom)
                    # Large diagrams stay at their actual SVG scale for genuine glyph clicks.
                    page.locator("svg").evaluate("e=>{const v=e.viewBox.baseVal;e.style.width=v.width+'px';e.style.height=v.height+'px'}")
                    page.locator("#canvas").evaluate("e=>e.style.overflow='auto'")
                    measured = page.evaluate((Path(__file__).parent / "measure.js").read_text())
                    checks = analyze(case, measured, data["code_urls"])
                    clicks = check_navigation(context, page, case, data["code_urls"]) if checks["passed"] else []
                    result = {"case":case.name,"repeat":repeat,"zoom":zoom,"geometry":checks,"clicks":clicks,
                              "passed":checks["passed"] and len(clicks)==len(case.blocks)+len(case.ports) and all(c["passed"] for c in clicks)}
                    report["runs"].append(result)
                    write(output / (name + f"-{zoom}-measured.json"), measured)
                    page.screenshot(path=str(output / (name + f"-{zoom}.png")))
                    write(output / "report.json", report)
                    if not result["passed"]:
                        print(json.dumps(result), flush=True)
                        context.close(); browser.close(); return 1
                context.close()
        browser.close()
    # Expected identities/topology are checked by the oracle on every compilation.
    report["passed"] = all(r["passed"] for r in report["runs"]) and len(report["runs"]) == 6 * len(selected_cases)
    write(output / "report.json", report)
    print(json.dumps({"passed":report["passed"],"runs":len(report["runs"])}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--elk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", choices=[c.name for c in cases()])
    a = parser.parse_args()
    raise SystemExit(run(a.bridge.resolve(), a.elk.resolve(), a.output.resolve(), a.case))
