"""Browser workflow tests (Playwright + the bundled Chromium). Mandatory under HX_REQUIRE_TOOLS=1.

They drive the real served viewer: layout on the minimized CVA6 graph, the forced-failure fallbacks, selection
restore, an SSE round trip observed in the DOM, source navigation to a distant call site, deleting a note through
the DOM, and wide parameter display."""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

import pytest

from conftest import require_tool

pw = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

HERE = os.path.dirname(__file__)
LAYOUT_FAIL = os.path.join(HERE, "fixtures", "viewer", "layout-fail.json")


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); return port


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:  # noqa: BLE001
            if os.environ.get("HX_REQUIRE_TOOLS"):
                pytest.fail(f"HX_REQUIRE_TOOLS=1: Playwright Chromium not available: {e}")
            pytest.skip(f"Playwright Chromium not installed: {e}")
        yield b
        b.close()


class Served:
    """`hx serve` in a thread (uvicorn) on a free port."""
    def __init__(self, graph_path, root=None):
        import uvicorn
        from hx.serve.app import create_app
        self.port = _free_port()
        self.app = create_app(str(graph_path), root=str(root) if root else None, poll_interval=0.05)
        self.cfg = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(self.cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        self.url = f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


def _open(browser, url, wait=2000):
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    requests = []
    page.on("request", lambda r: requests.append(r.url))
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(wait)
    return ctx, page, errors, requests


@pytest.fixture
def layout_fail_server(tmp_path):
    proj = tmp_path / "lf"; (proj / ".hx").mkdir(parents=True)
    shutil.copy(LAYOUT_FAIL, proj / ".hx" / "graph.json")
    s = Served(proj / ".hx" / "graph.json")
    yield s, proj
    s.stop()


def test_minimized_cva6_graph_lays_out_with_dagre_itself(browser, layout_fail_server):
    """The fixture is the smallest graph that threw 'Not possible to find intersection inside of the rectangle' in
    dagre 0.8.5. It must lay out with dagre proper (not a fallback) and without page errors."""
    s, _ = layout_fail_server
    ctx, page, errors, requests = _open(browser, s.url + "/#depth=9&layout=LR")
    t = page.evaluate("() => window.HX_TEST")
    assert errors == [] and t["lastLayout"] == "dagre", t                                     # dagre proper, file groups kept
    assert t["ranker"] == "network-simplex" and t["layoutErrors"] == [], t                     # first attempt, no retry needed
    assert page.evaluate("() => window.HX_DEBUG.state().cy.nodes(':parent').length") >= 5         # compounds are still there
    assert page.locator("#tree .row").count() >= 7
    assert any(u.endswith("/events") for u in requests)
    ctx.close()


@pytest.mark.parametrize("n,expected", [(2, "dagre-flat"), (3, "breadthfirst")])
def test_forced_layout_failures_fall_back_and_init_still_completes(browser, layout_fail_server, n, expected):
    s, _ = layout_fail_server
    ctx = browser.new_context(viewport={"width": 1500, "height": 950}); page = ctx.new_page()
    errors = []; page.on("pageerror", lambda e: errors.append(str(e)))
    requests = []; page.on("request", lambda r: requests.append(r.url))
    page.add_init_script(f"window.HX_TEST = {{failLayouts: {n}}};")
    sel = "sv:core/issue_stage.sv::cva6.issue_stage_i"
    page.goto(s.url + f"/#depth=9&layout=LR&kind=node&sel={sel}", wait_until="domcontentloaded"); page.wait_for_timeout(2500)
    t = page.evaluate("() => window.HX_TEST")
    assert errors == [] and t["lastLayout"] == expected and len(t["layoutErrors"]) == n, t   # n injected failures: network-simplex, longest-path[, flat]
    assert "layout fallback" in page.locator("#banner").inner_text()
    assert page.locator("#tree .row.sel").count() == 1 and page.locator("#tree .row.sel").get_attribute("title") == sel   # selection restored
    assert any(u.endswith("/events") for u in requests)                                                                  # live updates connected
    ctx.close()


@pytest.fixture
def c_server(cproj, extract):
    g = extract(depth=3)
    gp = cproj / ".hx" / "graph.json"
    g.save(str(gp))
    s = Served(gp, root=cproj)
    yield s, cproj
    s.stop()


def test_selection_restored_and_sse_round_trip_reaches_the_dom(browser, c_server):
    import httpx
    s, cproj = c_server
    nid = "c:src/dma.c::dma_start"
    ctx, page, errors, _ = _open(browser, s.url + f"/#depth=3&kind=node&sel={nid}")
    assert errors == [] and page.locator("#tree .row.sel").get_attribute("title") == nid
    assert page.locator("#detail textarea.note").input_value() == ""
    # an external writer (hx mcp, another browser) patches the annotations: the open page must show it, via SSE
    r = httpx.patch(s.url + "/api/annotations", json={"nodes": {nid: {"note": "written by another client"}}}, timeout=10)
    assert r.status_code == 200
    page.wait_for_function("() => document.querySelector('#detail textarea.note') && document.querySelector('#detail textarea.note').value.includes('another client')", timeout=8000)
    ctx.close()


def test_source_navigation_to_a_distant_call_site(browser, c_server):
    s, cproj = c_server
    nid = "c:src/main.c::app_run"
    ctx, page, errors, _ = _open(browser, s.url + f"/#depth=3&kind=node&sel={nid}")
    assert errors == []
    first = page.locator("#source-holder .ln").first.inner_text()
    link = page.locator("#detail span.muted.small.link").filter(has_text=":").first      # a call-site ":<line>" link
    link.click()
    page.wait_for_timeout(500)
    hl = page.locator("#source-holder .ln.hl")
    assert hl.count() == 1
    assert page.evaluate("() => { const el = document.querySelector('#source-holder .ln.hl'); const r = el.getBoundingClientRect(); const h = el.closest('#source-holder').getBoundingClientRect(); return r.top >= h.top - 1 && r.bottom <= h.bottom + 1; }")
    ctx.close()


def test_note_deleted_through_the_dom_stays_deleted_after_reload(browser, c_server):
    s, cproj = c_server
    nid = "c:src/dma.c::dma_start"
    ctx, page, errors, _ = _open(browser, s.url + f"/#depth=3&kind=node&sel={nid}")
    ta = page.locator("#detail textarea.note")
    ta.fill("temporary note"); ta.dispatch_event("change"); page.wait_for_timeout(900)
    assert json.load(open(cproj / ".hx" / "annotations.json"))["nodes"][nid]["note"] == "temporary note"
    ta.fill(""); ta.dispatch_event("change"); page.wait_for_timeout(900)
    assert nid not in json.load(open(cproj / ".hx" / "annotations.json"))["nodes"]
    page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(1500)
    assert page.locator("#detail textarea.note").input_value() == ""
    ctx.close()


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_wide_parameter_shows_the_literal_not_infinity(browser, tmp_path):
    from hx.api import extract as _extract
    src = os.path.join(HERE, "fixtures", "sv_adv")
    proj = tmp_path / "adv"; shutil.copytree(src, proj, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
    g = _extract("rtl/top_adv.sv:top_adv", root=str(proj), filelist=str(proj / "files.f"), top="top_adv", depth=1)
    gp = proj / ".hx" / "graph.json"; g.save(str(gp))
    s = Served(gp, root=proj)
    try:
        ctx, page, errors, _ = _open(browser, s.url + "/#depth=1&kind=node&sel=sv:rtl/top_adv.sv::top_adv")
        assert errors == []
        txt = page.locator("#detail").inner_text()
        assert "Infinity" not in txt and "CFG=" in txt and "16384'hffffffff…ffff" in txt
        full = page.locator("#detail dd span[title]").filter(has_text="16384'h").first.get_attribute("title")
        assert full.startswith("16384'h" + "f" * 4096)
        ctx.close()
    finally:
        s.stop()


# ---------------------------------------------------------------- hide / show (eye buttons)
def _drawn(page):
    return set(page.evaluate("() => window.HX_DEBUG.state().cy.nodes().not(':parent').map((n) => n.id())"))


def _drawn_edges(page):
    return page.evaluate("() => window.HX_DEBUG.state().cy.edges().map((e) => [e.data('source'), e.data('target')])")


def _ann(cproj):
    return json.load(open(cproj / ".hx" / "annotations.json"))


def test_hide_module_removes_it_and_what_only_it_reaches(browser, c_server):
    s, cproj = c_server
    dma_start, prog, w32, r32, poll = ("c:src/dma.c::dma_start", "c:src/dma.c::dma_prog_desc", "c:src/hal.c::hal_write32",
                                       "c:src/hal.c::hal_read32", "c:src/dma.c::dma_poll")
    ctx, page, errors, _ = _open(browser, s.url + "/#depth=3")
    assert {dma_start, prog, w32, r32, poll} <= _drawn(page)
    assert page.locator(f'#tree .row[title="{json.dumps("c:src/main.c::app_run")[1:-1]}"] .eye').count() == 0   # the entry has no eye
    page.locator(f'#tree .row[title="{dma_start}"] .eye').first.click()
    page.wait_for_timeout(900)
    drawn = _drawn(page)
    assert dma_start not in drawn and prog not in drawn and w32 not in drawn        # only reachable through dma_start
    assert r32 in drawn and poll in drawn                                          # still reached through dma_poll
    assert not any(dma_start in pair or prog in pair for pair in _drawn_edges(page))
    assert "hidden" in page.locator(f'#tree .row[title="{dma_start}"]').first.get_attribute("class")
    assert page.locator("#tree .tree-h").filter(has_text="hidden (1)").count() == 1
    assert _ann(cproj)["view"]["hidden"] == [dma_start]
    assert errors == []
    page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(1500)        # persisted
    assert dma_start not in _drawn(page) and w32 not in _drawn(page)
    page.locator(f'#tree .row[title="{dma_start}"] .eye').first.click()            # closed eye → show again
    page.wait_for_timeout(900)
    assert {dma_start, prog, w32} <= _drawn(page) and _ann(cproj)["view"]["hidden"] == []
    ctx.close()


def test_show_all_key_and_detail_button(browser, c_server):
    s, cproj = c_server
    poll, start = "c:src/dma.c::dma_poll", "c:src/dma.c::dma_start"
    ctx, page, errors, _ = _open(browser, s.url + f"/#depth=3&kind=node&sel={poll}")
    page.keyboard.press("h")                                                      # h hides the selected node
    page.wait_for_timeout(600)
    assert poll not in _drawn(page)
    assert page.locator("#detail button.hide-btn").inner_text() == "show module"
    page.locator(f'#tree .row[title="{start}"] .eye').first.click(); page.wait_for_timeout(600)
    assert start not in _drawn(page) and sorted(_ann(cproj)["view"]["hidden"]) == sorted([poll, start])
    page.locator("#tree .tree-h .link").filter(has_text="show all").click(); page.wait_for_timeout(900)
    assert {poll, start} <= _drawn(page) and _ann(cproj)["view"]["hidden"] == []
    page.locator("#detail button.hide-btn").click(); page.wait_for_timeout(600)   # detail pane button hides the selection
    assert poll not in _drawn(page) and page.locator("#detail button.hide-btn").inner_text() == "show module"
    assert page.locator("#tree .row.sel").count() == 1                             # a hidden node stays selectable
    assert errors == []
    ctx.close()


def test_hidden_state_carries_into_the_exported_page(browser, c_server, tmp_path):
    from hx.export import build_html
    s, cproj = c_server
    start = "c:src/dma.c::dma_start"
    graph = json.load(open(cproj / ".hx" / "graph.json"))
    html = build_html(graph, {"schema": "hx-ann/1", "nodes": {}, "types": {}, "globals": {}, "view": {"hidden": [start], "pinned_positions": {}}})
    out = tmp_path / "export.html"; out.write_text(html)
    ctx, page, errors, _ = _open(browser, "file://" + str(out))
    assert errors == [] and start not in _drawn(page) and "c:src/hal.c::hal_write32" not in _drawn(page)
    assert "hidden" in page.locator(f'#tree .row[title="{start}"]').first.get_attribute("class")
    page.locator(f'#tree .row[title="{start}"] .eye').first.click(); page.wait_for_timeout(300)
    assert start in _drawn(page) and not page.locator("#btn-download").is_hidden()   # export mode: edits are downloadable
    ctx.close()


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_hiding_an_instance_hides_its_subtree_but_not_shared_routines(browser, tmp_path):
    from hx.api import extract as _extract
    src = os.path.join(HERE, "fixtures", "sv")
    proj = tmp_path / "sv"; shutil.copytree(src, proj, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
    g = _extract("rtl/top.sv:top", root=str(proj), filelist=str(proj / "files.f"), top="top", depth=4)
    gp = proj / ".hx" / "graph.json"; g.save(str(gp))
    srv = Served(gp, root=proj)
    try:
        ctx, page, errors, _ = _open(browser, srv.url + "/#depth=4")
        core_a, alu_a, core_b, sat, add_len = ("sv:rtl/core.sv::top.u_core_a", "sv:rtl/alu.sv::top.u_core_a.u_alu", "sv:rtl/core.sv::top.u_core_b",
                                               "sv:rtl/core.sv::core.saturate", "sv:rtl/pkg.sv::dma_pkg.add_len")
        assert {core_a, alu_a, core_b, sat, add_len} <= _drawn(page)
        page.locator(f'#tree .row[title="{core_a}"] .eye').first.click(); page.wait_for_timeout(800)
        drawn = _drawn(page)
        assert core_a not in drawn and alu_a not in drawn                  # the module and its submodule
        assert core_b in drawn and sat in drawn and add_len in drawn       # the other core and the routines it still reaches
        assert errors == []
        ctx.close()
    finally:
        srv.stop()
