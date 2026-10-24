"""Repository examples use the real source viewer in Rust, C and Python."""

from copy import deepcopy
import json

import pytest

from d2_bridge.browser_check import click_links, oracle, running
from dev.d2_ports_experiment.geometry import analyze
from hx.architecture.presentation import payload
from test_d2_examples import d2_bridge, examples
from test_e2e_viewer import browser


@pytest.mark.parametrize(
    "identity", ["codex-paths", "codex-search", "ffmpeg-transcode", "hx-review"]
)
def test_gallery_real_multilanguage_navigation_and_measured_ports(
    examples, browser, identity
):
    case = examples.selected(identity)[0]
    graph = examples.prepare()
    nodes = json.loads(graph.read_text())["nodes"]
    with running(examples.app([case], graph)) as base:
        context = browser.new_context(viewport={"width": 1800, "height": 1100})
        page = context.new_page()
        try:
            page.goto(base + "/examples/" + identity)
            page.wait_for_function("window.HX_ARCH_READY || window.HX_ARCH_ERROR")
            assert not page.evaluate("window.HX_ARCH_ERROR")
            from d2_bridge.run import REPO

            measure = (REPO / "dev/d2_integration_experiment/measure.js").read_text()
            doc = examples.document(case, graph)
            for zoom in (1, 1.5):
                page.evaluate("z=>document.documentElement.style.zoom=String(z)", zoom)
                measured = analyze(
                    oracle(case),
                    page.evaluate(measure),
                    payload(doc, base + "/")["code_urls"],
                )
                assert measured["passed"], measured
            page.evaluate("document.documentElement.style.zoom='1'")
            page.locator("svg").evaluate(
                "e=>{const v=e.viewBox.baseVal;e.style.width=v.width+'px';e.style.height=v.height+'px'}"
            )
            page.locator("#canvas").evaluate("e=>e.style.overflow='auto'")
            selected = {
                **case,
                "blocks": case["blocks"][:1],
                "ports": case["ports"][-1:],
            }
            clicks = click_links(
                context, page, selected, nodes, examples.base / "sources"
            )
            assert len(clicks) == 2 and all(c["passed"] for c in clicks), clicks
            if identity == "ffmpeg-transcode":
                # A genuine click whose bound source metadata is wrong must fail.
                wrong = deepcopy(nodes)
                wrong[selected["ports"][0]["symbol"]]["signature"] = "wrong declaration"
                failed = click_links(
                    context,
                    page,
                    {**selected, "blocks": []},
                    wrong,
                    examples.base / "sources",
                )
                assert not failed[0]["passed"] and "signature" in failed[0]["error"]
        finally:
            context.close()


def test_gallery_exports_render_offline_without_source_fetches(examples, browser):
    cases = list(examples.cases.values())
    index = examples.export(cases)
    context = browser.new_context()
    page = context.new_page()
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    try:
        for case in cases:
            page.goto((index.parent / (case["id"] + ".html")).as_uri())
            page.wait_for_function("window.HX_ARCH_READY || window.HX_ARCH_ERROR")
            assert not page.evaluate("window.HX_ARCH_ERROR")
            assert "code navigation unavailable" in page.locator("#status").inner_text()
        assert not any(url.startswith(("http:", "https:")) for url in requests)
    finally:
        context.close()


def test_exported_port_link_opens_matching_live_gallery_source(examples, browser):
    case = examples.selected("ffmpeg-transcode")[0]
    graph = examples.prepare()
    nodes = json.loads(graph.read_text())["nodes"]
    with running(examples.app([case], graph)) as base:
        index = examples.export([case], code_url=base + "/")
        context = browser.new_context(viewport={"width": 1800, "height": 1100})
        page = context.new_page()
        try:
            page.goto((index.parent / (case["id"] + ".html")).as_uri())
            page.wait_for_function("window.HX_ARCH_READY || window.HX_ARCH_ERROR")
            assert not page.evaluate("window.HX_ARCH_ERROR")
            page.locator("svg").evaluate(
                "e=>{const v=e.viewBox.baseVal;e.style.width=v.width+'px';e.style.height=v.height+'px'}"
            )
            page.locator("#canvas").evaluate("e=>e.style.overflow='auto'")
            port = next(p for p in case["ports"] if p["id"] == "decode.frames")
            clicks = click_links(
                context,
                page,
                {**case, "blocks": [], "ports": [port]},
                nodes,
                examples.base / "sources",
            )
            assert len(clicks) == 1 and clicks[0]["passed"], clicks
            assert clicks[0]["file"] == "ffmpeg/libavcodec/avcodec.c"
        finally:
            context.close()
