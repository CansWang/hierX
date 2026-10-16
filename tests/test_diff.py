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
    assert {(x["name"], x["change"]) for x in tc["fields"]} == {("pad", "added"), ("y", "offset")}   # inserting pad is not a reorder of x,y
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


def test_params_and_attrs_compared_without_signature_change():
    """Review finding H7: a port direction flip or an HDL parameter change must show up even when the signature text is identical."""
    f = _node("c:a.c::f", "void f(x)", params=[("x", "logic", "in")])
    old = _graph([f])
    new = copy.deepcopy(old)
    new["nodes"][f["id"]]["params"][0]["dir"] = "out"
    new["nodes"][f["id"]]["attrs"] = {"parameters": {"W": 10}, "signals": [{"name": "s1", "type": "logic"}]}
    old["nodes"][f["id"]]["attrs"] = {"parameters": {"W": 8}, "signals": [{"name": "s0", "type": "logic"}, {"name": "s1", "type": "logic"}]}
    d = diff_graphs(old, new)
    ch = d["nodes"]["changed"][f["id"]]
    assert "signature" not in ch and ch["params"] == [{"name": "x", "change": "dir", "old": "in", "new": "out"}]
    assert ch["attrs"]["parameters.W"] == {"old": 8, "new": 10} and ch["attrs"]["signals"] == {"removed": ["s0"]}
    md = render_markdown(d)
    assert "param x dir in → out" in md and "attr parameters.W 8 → 10" in md and "attr signals −s0" in md


def test_edge_args_change_reported_even_when_a_call_is_added():
    f = _node("c:a.c::f", calls=["c:a.c::g"])
    g = _node("c:a.c::g")
    e = lambda args, line: {"from": f["id"], "to": g["id"], "kind": "call", "args": args, "loc": {"file": "a.c", "line": line}}
    old = _graph([f, g], edges=[e(["1"], 12)])
    new = _graph([f, g], edges=[e(["2"], 12), e(["3"], 13)])      # existing call's args changed AND a call added
    d = diff_graphs(old, new)
    assert d["summary"]["edges_added"] == 1 and d["summary"]["edges_args_changed"] == 1
    assert d["edges"]["args_changed"][0]["old_args"] == [["1"]] and sorted(d["edges"]["args_changed"][0]["new_args"]) == [["2"], ["3"]]


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


# ---------------------------------------------------------------- netlist graphs (hx/3 `circuit`, Phase N1)
def _spice_graphs(tmp_path):
    import shutil
    from hx.api import extract
    fix = os.path.join(os.path.dirname(__file__), "fixtures", "spice")
    a = tmp_path / "a"
    shutil.copytree(os.path.join(fix, "ota"), a)
    b = tmp_path / "b"
    shutil.copytree(os.path.join(fix, "ota_rewired_lib"), b)
    return (extract("ota.sp:.", root=str(a), depth=None, dialect="ngspice").to_dict(),
            extract("ota.sp:.", root=str(b), depth=None, dialect="ngspice").to_dict())


def test_spice_wiring_model_param_port_order(tmp_path):
    old, new = _spice_graphs(tmp_path)
    d = diff_graphs(old, new)
    s = d["summary"]
    assert any(e["from"] == "sp:ota.sp::(deck) ota.sp" and e["to"] == "sp:ota.sp::xb" for e in d["edges"]["args_changed"])   # instance rewired
    port_wiring = {w["terminal"]: (w["old"], w["new"]) for w in d["nodes"]["changed"]["sp:ota.sp::xb"]["wiring"]}
    assert port_wiring == {"vip": ("vin", "vip"), "vin": ("vip", "vin")}                   # the nets behind XB's ports swapped
    assert "wiring" not in d["nodes"]["changed"].get("sp:ota.sp::xa", {})                 # XA is wired as before
    assert "wiring" not in d["nodes"]["changed"].get("sp:ota.sp::xb.xm_in1", {})          # XB's rewiring is reported on XB only, not on its children
    assert "wiring" not in d["nodes"]["changed"]["sp:ota.sp::xa.xm_in1"]
    assert new["circuit"]["ports"]["sp:ota.sp::xb.xm_in1"][1]["net"] == "vip"               # the canonical net is still there to read
    assert {w["terminal"] for w in d["nodes"]["changed"]["sp:ota.sp::xa.x_cm"]["wiring"]} == {"tail", "ibias"}   # cm's new port order rewires an unchanged X line
    m = d["nodes"]["changed"]["sp:ota.sp::xa.m_load_1"]
    assert m["attrs"]["model"] == {"old": "pch", "new": "pch_hv"}                          # model change
    xin = d["nodes"]["changed"]["sp:ota.sp::xa.xm_in1"]
    assert xin["attrs"]["parameters.w"] == {"old": "2u", "new": "3u"}                       # instance parameter change
    cm = d["nodes"]["changed"]["sp:ota.sp::xa.x_cm"]
    assert any(p["change"] == "reordered" for p in cm["params"])                           # port order change
    assert s["wiring_changed"] >= 1 and s["any"]
    md = render_markdown(d, new)
    assert "wiring vip vin → vip" in md and "## Circuit" in md


def test_spice_model_card_and_param_definition_changes(tmp_path):
    old, new = _spice_graphs(tmp_path)
    d = diff_graphs(old, new)
    c = d["circuit"]
    assert [x["key"] for x in c["models"]["changed"]] == ["/nch"]                           # an edited .model card, names unchanged
    assert [x["key"] for x in c["params"]["changed"]] == ["/ibias_val"]
    assert {x["key"] for x in c["definitions"]["changed"]} == {"/cm", "/five_t_opamp"}     # port order edits the definition
    assert [x for x in c["models"]["added"]] == ["/pch_hv"] and d["summary"]["models_changed"] == 2 and d["summary"]["cparams_changed"] == 1
    md = render_markdown(d, new)
    assert "~ model /nch" in md and "~ param /ibias_val" in md


def test_spice_edit_confined_to_one_model_branch(tmp_path):
    import copy as _copy
    import shutil
    from hx.api import extract
    fix = os.path.join(os.path.dirname(__file__), "fixtures", "spice", "conditional")
    a = tmp_path / "a"
    shutil.copytree(fix, a)
    old = extract("cond.sp:.", root=str(a), depth=None, dialect="ngspice").to_dict()
    p = a / "cond.sp"
    p.write_text(p.read_text().replace(".model dm d is=3e-14", ".model dm d is=4e-14"))      # the .else branch only
    new = extract("cond.sp:.", root=str(a), depth=None, dialect="ngspice", use_cache=False).to_dict()
    d = diff_graphs(old, new)
    changed = d["circuit"]["models"]["changed"]
    assert len(changed) == 1 and changed[0]["key"].startswith("/dm#") and d["summary"]["models_changed"] == 1
    assert set(d["nodes"]["changed"]) == {"sp:cond.sp::(deck) cond.sp"}                   # the deck scope's hash moved; no device or instance changed


def test_spice_ancestor_rewiring_is_reported_once(tmp_path):
    """Swapping the nets of the two guarded `xw` lines rewires `xw` (both occurrences) and nothing below it."""
    import shutil
    from hx.api import extract
    fix = os.path.join(os.path.dirname(__file__), "fixtures", "spice", "conditional")
    a = tmp_path / "a"
    shutil.copytree(fix, a)
    old = extract("nested_guard.sp:.", root=str(a), depth=None, dialect="ngspice").to_dict()
    p = a / "nested_guard.sp"
    p.write_text(p.read_text().replace("xw n1 n2 wrap\n.else\nxw n2 n1 wrap", "xw n2 n1 wrap\n.else\nxw n1 n2 wrap"))
    new = extract("nested_guard.sp:.", root=str(a), depth=None, dialect="ngspice", use_cache=False).to_dict()
    d = diff_graphs(old, new)
    wired = sorted(nid.split("::")[1] for nid, ch in d["nodes"]["changed"].items() if "wiring" in ch)
    assert len(wired) == 2 and all(w.startswith("xw#") for w in wired) and d["summary"]["wiring_changed"] == 2
    assert not d["nodes"]["added"] and not d["nodes"]["removed"]


def test_spice_else_branch_edit_of_a_per_branch_model_registers(tmp_path):
    """A model and a definition used only inside their own branch: editing the `.else` ones moves exactly their keys."""
    import shutil
    from hx.api import extract
    fix = os.path.join(os.path.dirname(__file__), "fixtures", "spice", "conditional")
    a = tmp_path / "a"
    shutil.copytree(fix, a)
    old = extract("per_branch.sp:.", root=str(a), depth=None, dialect="ngspice").to_dict()
    p = a / "per_branch.sp"
    p.write_text(p.read_text().replace(".model dm d is=2e-14", ".model dm d is=5e-14").replace("r1 a b 2k", "r1 a b 3k"))
    new = extract("per_branch.sp:.", root=str(a), depth=None, dialect="ngspice", use_cache=False).to_dict()
    d = diff_graphs(old, new)
    c = d["circuit"]
    assert [x["key"].split("#")[0] for x in c["models"]["changed"]] == ["/dm"] and "#" in c["models"]["changed"][0]["key"]
    assert [x["key"].split("#")[0] for x in c["definitions"]["changed"]] == ["/leaf"] and "#" in c["definitions"]["changed"][0]["key"]
    assert d["summary"]["models_changed"] == 1 and d["summary"]["cdefs_changed"] == 1 and "params" not in c
    gid = c["models"]["changed"][0]["key"].split("#")[1]
    assert c["definitions"]["changed"][0]["key"].endswith("#" + gid)                         # the same (else) branch


def test_spice_condition_edit_changes_the_enclosing_scopes(tmp_path):
    import shutil
    from hx.api import extract
    fix = os.path.join(os.path.dirname(__file__), "fixtures", "spice", "conditional")
    a = tmp_path / "a"
    shutil.copytree(fix, a)
    old = extract("cond.sp:.", root=str(a), depth=None, dialect="ngspice").to_dict()
    p = a / "cond.sp"
    p.write_text(p.read_text().replace("(pick > 0)", "(pick > 1)").replace("(pick>0)", "(pick>1)"))
    new = extract("cond.sp:.", root=str(a), depth=None, dialect="ngspice", use_cache=False).to_dict()
    d = diff_graphs(old, new)
    assert {"sp:cond.sp::(deck) cond.sp", "sp:cond.sp::xw"} <= set(d["nodes"]["changed"])     # the scopes holding the conditionals
    assert d["nodes"]["added"] and d["nodes"]["removed"]                                       # guarded occurrences carry new guard ids
