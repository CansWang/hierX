"""MCP tools over the in-memory client against graphs produced on the C fixture."""
import asyncio
import os

import pytest

pytest.importorskip("mcp")
from mcp.client import Client  # noqa: E402

from hx import project  # noqa: E402
from hx.mcp_server import build_server  # noqa: E402


def _text(result):
    return "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")


async def _call(server, name, args):
    async with Client(server) as c:
        return _text(await c.call_tool(name, args))


def test_tools_end_to_end(cproj):
    root = str(cproj)
    project.track(root, "src/main.c:app_run", depth=3, jobs=1)
    project.update(root)
    srv = build_server(root)

    async def go():
        async with Client(srv) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"list_graphs", "get_function", "callees", "callers", "get_type", "search", "diff_since", "extract", "annotate"} <= names
            out = {}
            out["graphs"] = _text(await c.call_tool("list_graphs", {}))
            out["fn"] = _text(await c.call_tool("get_function", {"id": "c:src/dma.c::dma_start"}))
            out["fn_by_name"] = _text(await c.call_tool("get_function", {"id": "dma_poll"}))
            out["callees"] = _text(await c.call_tool("callees", {"id": "c:src/main.c::app_run", "depth": 3}))
            out["callers"] = _text(await c.call_tool("callers", {"id": "c:src/hal.c::hal_write32"}))
            out["type"] = _text(await c.call_tool("get_type", {"id": "dma_chan_t"}))
            out["search"] = _text(await c.call_tool("search", {"query": "dma_"}))
            out["diff0"] = _text(await c.call_tool("diff_since", {}))
            out["ann"] = _text(await c.call_tool("annotate", {"id": "c:src/dma.c::dma_start", "note": "agent: touched", "tags": "dma, hot"}))
            out["fn2"] = _text(await c.call_tool("get_function", {"id": "c:src/dma.c::dma_start"}))
            out["extract"] = _text(await c.call_tool("extract", {"entry": "src/hal.c:hal_read32", "depth": 1}))
            out["graphs2"] = _text(await c.call_tool("list_graphs", {}))
            return out
    out = asyncio.run(go())
    assert project.slug("src/main.c:app_run") in out["graphs"] and "c:src/main.c::app_run" in out["graphs"]
    assert "int dma_start(dma_chan_t * ch, const uint8_t * buf, size_t len)" in out["fn"]
    assert "ch: dma_chan_t * [inout heuristic] -> c:include/dma.h::dma_chan_t" in out["fn"]
    assert "globals: reads src/dma.c::g_dma_active, src/dma.c::g_dma_max; writes src/dma.c::g_dma_active" in out["fn"]
    assert "fnptr    (ch->cb)(ch->cb_ctx, rc)" in out["fn"] and "called by: src/main.c::app_run" in out["fn"]
    assert out["fn_by_name"].startswith("c:src/dma.c::dma_poll")
    assert "call     src/dma.c::dma_start" in out["callees"] and "    macro    src/hal.c::hal_write32" in out["callees"]
    assert "src/dma.c::dma_prog_desc  macro(ch->base, ch->desc.src)" in out["callers"]
    assert "c:include/dma.h::dma_chan_t  [typedef, size 56" in out["type"] and ".desc: struct dma_desc @8+12" in out["type"]
    assert "function c:src/dma.c::dma_start" in out["search"] and "type     c:include/dma.h::struct dma_desc" in out["search"]
    assert "no history" in out["diff0"]
    assert "annotated c:src/dma.c::dma_start" in out["ann"] and "note: agent: touched" in out["fn2"] and "tags: dma, hot" in out["fn2"]
    assert out["extract"].startswith(f"graph {project.slug('src/hal.c:hal_read32')}: c:src/hal.c::hal_read32  1 functions")
    assert project.slug("src/hal.c:hal_read32") in out["graphs2"]
    # second update creates history; diff_since now reports
    dma_c = cproj / "src" / "dma.c"
    dma_c.write_text(dma_c.read_text().replace("    g_dma_active++;\n", "    g_dma_active += 1;\n    hal_read32(ch->base);\n"))
    import time
    os.utime(dma_c, (time.time() + 5, time.time() + 5))
    project.update(root, ["src/main.c:app_run"])
    txt = asyncio.run(_call(srv, "diff_since", {"graph": project.slug("src/main.c:app_run")}))
    assert "calls +hal_read32" in txt and "since" in txt


def test_errors_are_messages_not_exceptions(cproj):
    srv = build_server(str(cproj))
    assert "No graphs" in asyncio.run(_call(srv, "list_graphs", {}))
    txt = asyncio.run(_call(srv, "get_function", {"id": "x"}))
    assert "no graphs yet" in txt.lower() or "error" in txt.lower()
