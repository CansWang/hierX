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


def test_extract_uses_tracked_netlist_options(tmp_path):
    """MCP `extract`: an omitted option takes the tracked entry's value; an explicit value, including depth=3 or
    include_callers=false, overrides it; track=true persists the merged table (Phase N1, every language)."""
    import json
    import shutil
    fix = os.path.join(os.path.dirname(__file__), "fixtures", "spice", "ota")
    root = tmp_path / "sp"
    shutil.copytree(fix, root, ignore=shutil.ignore_patterns(".hx"))
    root = str(root)
    entry = "ota.sp:xa.x_cm.xref"
    project.track(root, entry, depth=1, include_callers=True, dialect="ngspice", search_paths=["lib"])
    srv = build_server(root)

    def args():
        return json.load(open(project.graph_path(root, entry)))["meta"]["extract_args"]
    txt = asyncio.run(_call(srv, "extract", {"entry": entry}))                                   # everything omitted
    assert txt.startswith(f"graph {project.slug(entry)}: sp:ota.sp::xa.x_cm.xref"), txt
    a = args()
    assert a["dialect"] == "ngspice" and a["search_paths"] == ["lib"] and a["depth"] == 1 and a["include_callers"] is True
    asyncio.run(_call(srv, "extract", {"entry": entry, "depth": 3}))                             # explicit 3 beats tracked 1
    a = args()
    assert a["depth"] == 3 and a["dialect"] == "ngspice" and a["include_callers"] is True
    asyncio.run(_call(srv, "extract", {"entry": entry, "include_callers": False, "track": True}))   # explicit False beats tracked True
    a = args()
    assert a["include_callers"] is False and a["depth"] == 1 and a["dialect"] == "ngspice" and a["search_paths"] == ["lib"]
    cfg = next(e for e in project.load_config(root)["entries"] if e["entry"] == entry)
    assert cfg["dialect"] == "ngspice" and cfg["search_paths"] == ["lib"] and cfg["depth"] == 1 and not cfg.get("include_callers")
    txt = asyncio.run(_call(srv, "extract", {"entry": "ota.sp:nope"}))
    assert txt.startswith("extract failed: EntryNotFound")


def test_lookup_ambiguity_query_errors_search_kind_and_history_points(cproj, monkeypatch):
    """The documented 'ambiguous; candidates' answers, the netlist tools on a graph without circuit data, kind-filtered
    search, a timestamp for diff_since, and a save failure reported as text."""
    root = str(cproj)
    project.track(root, "src/main.c:app_run", depth=3, jobs=1)
    project.update(root)
    gp = project.graph_path(root, "src/main.c:app_run")
    import json
    g = json.load(open(gp))
    twin = dict(g["nodes"]["c:src/dma.c::dma_start"], id="c:src/other.c::dma_start")
    g["nodes"][twin["id"]] = twin
    tid = next(t for t in g["types"] if t.endswith("struct dma_chan"))
    g["types"]["c:include/other.h::struct dma_chan"] = dict(g["types"][tid], id="c:include/other.h::struct dma_chan")
    with open(gp, "w") as fh:
        json.dump(g, fh)
    srv = build_server(root)
    out = asyncio.run(_call(srv, "get_function", {"id": "dma_start"}))
    assert out.startswith("ambiguous; candidates:") and "c:src/other.c::dma_start" in out and "c:src/dma.c::dma_start" in out
    out = asyncio.run(_call(srv, "get_type", {"id": "struct dma_chan"}))
    assert out.startswith("ambiguous; candidates:") and "c:include/other.h::struct dma_chan" in out
    assert asyncio.run(_call(srv, "get_type", {"id": "struct nope"})).startswith("type not in graph")
    for tool, args in (("get_net", {"net": "vdd"}), ("netlist_uses", {"target": "/amp", "kind": "definition"})):
        out = asyncio.run(_call(srv, tool, args))
        assert "no circuit data" in out and "extract a netlist first" in out
    types_only = asyncio.run(_call(srv, "search", {"query": "dma", "kind": "type"}))
    assert "struct dma_chan" in types_only and "c:src/dma.c::dma_start" not in types_only
    assert asyncio.run(_call(srv, "diff_since", {"since": "2000-01-01T00:00:00Z"})).startswith("no history for")
    project.snapshot(root, "src/main.c:app_run", gp)
    out = asyncio.run(_call(srv, "diff_since", {"since": "2000-01-01T00:00:00Z"}))
    assert out.startswith("# ") and " since " in out.splitlines()[0]                    # the earliest snapshot is used

    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(project, "save_extraction", boom)
    out = asyncio.run(_call(srv, "extract", {"entry": "src/hal.c:hal_write32", "depth": 1}))
    assert out == "save failed: disk full"
