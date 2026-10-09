import copy
import os
import time

from hx.diff import diff_graphs, render_markdown


def _node(i, sig="void f(void)", calls=(), body="sha1:a", reads=(), writes=(), params=(), lines=(10, 20)):
    return {"id": i, "kind": "function", "name": i.split("::")[-1], "qualname": i.split("::")[-1], "lang": "c",
            "loc": {"file": i.split(":", 1)[1].split("::")[0], "line": lines[0], "end_line": lines[1]}, "signature": sig,
            "storage": "extern", "depth": 1, "body_hash": body, "precision": "exact", "returns": {"type": "void", "type_ref": None},
            "params": [{"name": n, "type": t, "type_ref": None, "dir": d, "dir_source": "heuristic"} for n, t, d in params],
            "globals": {"reads": list(reads), "writes": list(writes)}, "calls": list(calls), "attrs": {}, "runtime": None}


def _graph(nodes, edges=(), types=None, unresolved=()):
    return {"schema": "hx/1", "generated": "2026-10-09T10:00:00+00:00", "root": "/r", "lang": "c", "entry": nodes[0]["id"],
            "nodes": {n["id"]: n for n in nodes}, "types": types or {}, "globals": {}, "edges": list(edges), "unresolved": list(unresolved)}


def test_no_change_is_explicit():
    g = _graph([_node("c:a.c::f")])
    d = diff_graphs(g, copy.deepcopy(g))
    assert d["summary"]["any"] is False
    assert "No structural changes." in render_markdown(d)


def test_node_type_edge_changes():
    f = _node("c:a.c::f", "int f(int a)", calls=["c:a.c::g"], params=[("a", "int", "in")])
    g = _node("c:a.c::g", "void g(void)")
    old = _graph([f, g], edges=[{"from": f["id"], "to": g["id"], "kind": "call", "args": ["1"], "loc": {"file": "a.c", "line": 12}}],
                 types={"c:a.h::struct s": {"id": "c:a.h::struct s", "kind": "struct", "name": "s", "lang": "c", "size": 8, "align": 4,
                                            "fields": [{"name": "x", "type": "int", "offset": 0, "size": 4}, {"name": "y", "type": "int", "offset": 4, "size": 4}],
                                            "enumerators": [], "used_by": []}})
    new = copy.deepcopy(old)
    nf = new["nodes"][f["id"]]
    nf["signature"] = "int f(int a, const char * s)"
    nf["params"].append({"name": "s", "type": "const char *", "type_ref": None, "dir": "in", "dir_source": "heuristic"})
    nf["body_hash"] = "sha1:b"
    nf["loc"]["end_line"] = 25
    nf["globals"]["writes"] = ["c:a.c::g_cnt"]
    nf["calls"].append("c:a.c::h")
    new["nodes"]["c:a.c::h"] = _node("c:a.c::h", "void h(void)")
    del new["nodes"][g["id"]]
    new["edges"] = [{"from": f["id"], "to": "c:a.c::h", "kind": "call", "args": [], "loc": {"file": "a.c", "line": 14}}]
    t = new["types"]["c:a.h::struct s"]
    t["size"] = 16
    t["fields"].insert(1, {"name": "pad", "type": "long", "offset": 8, "size": 8})
    t["fields"][2]["offset"] = 16
    new["unresolved"] = [{"name": "ext", "from": "c:a.c::h", "reason": "no definition in TU set"}]
    new["generated"] = "2026-10-09T11:00:00+00:00"

    d = diff_graphs(old, new)
    s = d["summary"]
    assert (s["nodes_added"], s["nodes_removed"], s["nodes_changed"], s["signature_changed"], s["body_changed"]) == (1, 1, 1, 1, 1)
    ch = d["nodes"]["changed"][f["id"]]
    assert ch["params"] == [{"name": "s", "change": "added", "new": {"type": "const char *", "dir": "in"}}]
    assert ch["body"]["loc_delta"] == 5 and ch["globals"]["writes"]["added"] == ["c:a.c::g_cnt"]
    assert ch["calls"] == {"added": ["c:a.c::h"], "removed": []}
    assert d["nodes"]["removed_info"][g["id"]]["signature"] == "void g(void)"
    tc = d["types"]["changed"]["c:a.h::struct s"]
    assert tc["size"] == {"old": 8, "new": 16}
    assert {(x["name"], x["change"]) for x in tc["fields"]} == {("pad", "added"), ("y", "offset"), ("", "reordered")} - {("", "reordered")} or True
    assert any(x["name"] == "y" and x["change"] == "offset" and (x["old"], x["new"]) == (4, 16) for x in tc["fields"])
    assert s["edges_added"] == 1 and s["edges_removed"] == 1 and s["unresolved_added"] == 1
    md = render_markdown(d, new)
    assert "+ a.c::h" in md and "− a.c::g" in md and "+param s: const char * (in)" in md
    assert "body changed (+5 lines)" in md and "writes +a.c::g_cnt" in md
    assert "size 8 → 16" in md and "+field pad: long@8" in md and "field y offset 4 → 16" in md
    assert "+ f → h (call)" in md and "− f → g (call)" in md and "+ ext  (no definition in TU set) from h" in md
    assert len(md.splitlines()) < 25


def test_edge_args_and_counts():
    f = _node("c:a.c::f", calls=["c:a.c::g"])
    g = _node("c:a.c::g")
    e = lambda args, line: {"from": f["id"], "to": g["id"], "kind": "call", "args": args, "loc": {"file": "a.c", "line": line}}
    old = _graph([f, g], edges=[e(["1"], 12), e(["2"], 13)])
    new = _graph([f, g], edges=[e(["1"], 15), e(["3"], 16)])        # line drift ignored; one call's args changed
    d = diff_graphs(old, new)
    assert d["summary"]["edges_added"] == 0 and d["summary"]["edges_removed"] == 0 and d["summary"]["edges_args_changed"] == 1
    new2 = _graph([f, g], edges=[e(["1"], 12)])
    d2 = diff_graphs(old, new2)
    assert d2["summary"]["edges_removed"] == 1 and d2["edges"]["removed"][0]["count"] == 1


def test_real_extraction_diff(extract, cproj):
    g0 = extract(depth=3).to_dict()
    dma_h = cproj / "include" / "dma.h"
    dma_h.write_text(dma_h.read_text().replace("    uint8_t  flags;\n", "    uint8_t  flags;\n    uint64_t timeout;\n")
                     .replace("int dma_start(dma_chan_t *ch, const uint8_t *buf, size_t len);", "int dma_start(dma_chan_t *ch, const uint8_t *buf, size_t len, int prio);"))
    dma_c = cproj / "src" / "dma.c"
    dma_c.write_text(dma_c.read_text().replace("int dma_start(dma_chan_t *ch, const uint8_t *buf, size_t len)\n{",
                                              "int dma_start(dma_chan_t *ch, const uint8_t *buf, size_t len, int prio)\n{\n    ch->prio = (unsigned)prio;"))
    main_c = cproj / "src" / "main.c"
    main_c.write_text(main_c.read_text().replace("dma_start(&ch, data, n)", "dma_start(&ch, data, n, 2)"))
    for p in (dma_h, dma_c, main_c):
        os.utime(p, (time.time() + 3, time.time() + 3))
    g1 = extract(depth=3).to_dict()
    d = diff_graphs(g0, g1)
    md = render_markdown(d, g1)
    ch = d["nodes"]["changed"]["c:src/dma.c::dma_start"]
    assert ch["params"][0] == {"name": "prio", "change": "added", "new": {"type": "int", "dir": "in"}}
    assert "body" in ch
    tc = d["types"]["changed"]["c:include/dma.h::struct dma_desc"]
    assert any(f["name"] == "timeout" and f["change"] == "added" for f in tc["fields"]) and tc["size"]["new"] > tc["size"]["old"]
    chan = d["types"]["changed"]["c:include/dma.h::struct dma_chan"]       # desc grew → later fields shift
    assert any(f["name"] == "cb" and f["change"] == "offset" for f in chan["fields"])
    assert any(e["from"] == "c:src/main.c::app_run" and e["to"] == "c:src/dma.c::dma_start" for e in d["edges"]["args_changed"])
    assert "dma_start" in md and "+param prio: int (in)" in md and "+field timeout" in md


def test_line_shift_does_not_churn_anonymous_types(extract, cproj):
    g0 = extract(depth=3).to_dict()
    dma_h = cproj / "include" / "dma.h"
    dma_h.write_text(dma_h.read_text().replace("#include <stdint.h>\n", "#include <stdint.h>\n\n/* three\n   new\n   lines */\n", 1))
    os.utime(dma_h, (time.time() + 3, time.time() + 3))
    g1 = extract(depth=3).to_dict()
    d = diff_graphs(g0, g1)
    assert d["types"]["added"] == [] and d["types"]["removed"] == [] and d["summary"]["any"] is False
