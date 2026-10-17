"""hx/2 -> hx/3: the upgrade report, node/ghost/type id mapping (never guessed) and persistent project migration."""
import copy
import json
import os
import shutil
import sys

import pytest

from hx import annotations as A
from hx import graphio, project
from hx.model import SchemaError

sys.path.insert(0, os.path.dirname(__file__))
from test_clang_scoped import _project as _scoped_project  # noqa: E402

LEGACY = os.path.join(os.path.dirname(__file__), "fixtures", "legacy")
ORCH = os.path.join(LEGACY, "hx2-apragma-orchestrator.json")
DEVICE = os.path.join(LEGACY, "hx2-apragma-device-evaluate.json")
DEVICE3 = os.path.join(LEGACY, "hx3-apragma-device-evaluate.json")      # the same entry extracted by the fixed hx (hx/3)
FIXPY = os.path.join(os.path.dirname(__file__), "fixtures", "python")
PYRIGHT = shutil.which("pyright-langserver")
STUB = "py:/venv/site-packages/pyright/dist/typeshed-fallback/stdlib/builtins.pyi"


def _doc(**over):
    d = {"schema": "hx/2", "generated": "t", "root": "/root", "lang": "py", "entry": "py:a.py::outer", "nodes": {}, "types": {},
         "globals": {}, "edges": [], "unresolved": [], "meta": {}}
    d.update(over)
    return d


def _node(nid, kind, name, file, line, end_line=None, lang="py", precision="lsp", qualname=None):
    return {"id": nid, "kind": kind, "name": name, "qualname": qualname or name, "lang": lang, "precision": precision,
            "loc": {"file": file, "line": line, "end_line": end_line or line, "col": 1}, "signature": "", "storage": None,
            "depth": 0, "body_hash": "sha1:0", "returns": None, "params": [], "globals": {"reads": [], "writes": []},
            "calls": [], "attrs": {}, "runtime": None}


def test_upgrade_2_to_3_reports_nested_and_module_ids():
    nodes = {
        "py:a.py::outer": _node("py:a.py::outer", "function", "outer", "a.py", 1, 20),
        "py:a.py::helper#abcd1234": _node("py:a.py::helper#abcd1234", "function", "helper", "a.py", 5, 7),
        "py:a.py::helper": _node("py:a.py::helper", "function", "helper", "a.py", 12, 14),
        "py:b.py::top": _node("py:b.py::top", "function", "top", "b.py", 1, 3),
        "py:m.py::(module) m.py": _node("py:m.py::(module) m.py", "function", "(module) m.py", "m.py", 1),
        "c:/abs/build/src/x.c::f": _node("c:/abs/build/src/x.c::f", "function", "f", "/abs/build/src/x.c", 3, lang="c", precision="exact"),
        "c:/usr/include/stdio.h::printf": _node("c:/usr/include/stdio.h::printf", "function", "printf", "/usr/include/stdio.h", 3, lang="c", precision="exact"),
        "c:src/y.c::g": _node("c:src/y.c::g", "function", "g", "src/y.c", 3, lang="c", precision="exact"),
    }
    doc, rep = graphio.upgrade(_doc(nodes=nodes))
    assert doc["schema"] == "hx/4" and rep.from_schema == "hx/2" and rep.pending
    reasons = {x["id"]: x["reason"] for x in rep.needs_reextract}
    assert "position-hashed" in reasons["py:a.py::helper#abcd1234"]
    assert "nested in py:a.py::outer" in reasons["py:a.py::helper"]
    assert "module caller" in reasons["py:m.py::(module) m.py"]
    assert "absolute path" in reasons["c:/abs/build/src/x.c::f"]
    assert "lsp graph" in reasons["py:a.py::outer"]                     # the entry carries the conservative whole-graph flag
    assert "py:b.py::top" not in reasons and "c:/usr/include/stdio.h::printf" not in reasons and "c:src/y.c::g" not in reasons
    assert doc["meta"]["migration"]["from"] == "hx/2"
    with pytest.raises(SchemaError):
        graphio.upgrade(_doc(schema="hx/5"))


def test_upgrade_2_to_3_flags_hashless_nested_ids():
    """The saved Device.evaluate graph: `Device._interp_with` (line 690) sits inside `Device.evaluate` (340-756) with no
    hash, yet its hx/3 id becomes `Device.evaluate._interp_with`."""
    doc, rep = graphio.load_graph_with_report(DEVICE)
    assert doc["schema"] == "hx/4" and rep.from_schema == "hx/2"
    reasons = {x["id"]: x["reason"] for x in rep.needs_reextract}
    nested = "py:src/apragma/circuit_model/device.py::Device._interp_with"
    assert nested in reasons and "nested in py:src/apragma/circuit_model/device.py::Device.evaluate" in reasons[nested]
    assert "lsp graph" in reasons[doc["entry"]]


def test_map_node_ids():
    old = _doc(nodes={
        "py:a.py::helper#abcd1234": _node("py:a.py::helper#abcd1234", "function", "helper", "a.py", 5),
        "py:a.py::helper": _node("py:a.py::helper", "function", "helper", "a.py", 12),
        "py:m.py::(module) m.py": _node("py:m.py::(module) m.py", "function", "(module) m.py", "m.py", 1),
        "c:/root/src/x.c::f": _node("c:/root/src/x.c::f", "function", "f", "/root/src/x.c", 3, lang="c", precision="exact"),
        "py:a.py::twins": _node("py:a.py::twins", "function", "twins", "a.py", 40),
        "py:a.py::gone": _node("py:a.py::gone", "function", "gone", "a.py", 99),
        "py:a.py::same": _node("py:a.py::same", "function", "same", "a.py", 60),
        "py:a.py::A.x": _node("py:a.py::A.x", "function", "x", "a.py", 70, qualname="A.x"),
        "py:a.py::C.y": _node("py:a.py::C.y", "function", "y", "a.py", 80, qualname="C.y"),
    }, globals={"py:a.py::G": {"id": "py:a.py::G", "name": "G", "loc": {"file": "a.py", "line": 2}}})
    new = _doc(schema="hx/3", nodes={
        "py:a.py::outer.helper": _node("py:a.py::outer.helper", "function", "helper", "a.py", 5, qualname="outer.helper"),
        "py:a.py::other.helper": _node("py:a.py::other.helper", "function", "helper", "a.py", 12, qualname="other.helper"),
        "py:m.py::(module) m.py": _node("py:m.py::(module) m.py", "module", "(module) m.py", "m.py", 1),
        "c:src/x.c::f": _node("c:src/x.c::f", "function", "f", "src/x.c", 3, lang="c", precision="exact"),
        "py:a.py::p.twins": _node("py:a.py::p.twins", "function", "twins", "a.py", 40, qualname="p.twins"),
        "py:a.py::q.twins": _node("py:a.py::q.twins", "function", "twins", "a.py", 40, qualname="q.twins"),
        "py:a.py::same": _node("py:a.py::same", "function", "same", "a.py", 60),
        "py:a.py::A.B.x": _node("py:a.py::A.B.x", "function", "x", "a.py", 70, qualname="A.B.x"),     # scope gained inside A
        "py:a.py::D.C.y": _node("py:a.py::D.C.y", "function", "y", "a.py", 80, qualname="D.C.y"),     # a different enclosing scope
    }, globals={"py:a.py::G": {"id": "py:a.py::G", "name": "G", "loc": {"file": "a.py", "line": 2}}})
    mapped, ambiguous, unmapped = project.map_node_ids(old, new, "/root")
    assert mapped["py:a.py::A.x"] == "py:a.py::A.B.x"
    assert mapped["py:a.py::helper#abcd1234"] == "py:a.py::outer.helper"
    assert mapped["py:a.py::helper"] == "py:a.py::other.helper"
    assert mapped["py:m.py::(module) m.py"] == "py:m.py::(module) m.py"
    assert mapped["c:/root/src/x.c::f"] == "c:src/x.c::f"
    assert mapped["py:a.py::same"] == "py:a.py::same" and mapped["py:a.py::G"] == "py:a.py::G"
    assert ambiguous == {"py:a.py::twins": ["py:a.py::p.twins", "py:a.py::q.twins"]}
    assert sorted(u["id"] for u in unmapped) == ["py:a.py::C.y", "py:a.py::gone"]


def _ghost(uid, frm, line, col=1, file="src/apragma/x.py", family=None):
    u = {"name": uid.split("::")[-1].split("#")[0].split(".")[-1], "from": frm, "reason": "outside project root (library)",
         "loc": {"file": file, "line": line, "end_line": line, "col": col}, "id": uid}
    if family:
        u["family"] = family
    return u


def _rewrite_ghosts(doc, fn):
    """Apply `fn(old_id) -> (new_id, family | None)` to every unresolved record AND every edge target: the saved graphs
    reference a ghost from both, and a migration's new graph does the same."""
    ids = {}
    for u in doc["unresolved"]:
        if u.get("id"):
            nid, fam = fn(u["id"])
            ids[u["id"]] = nid
            u["id"] = nid
            if fam:
                u["family"] = fam
    for e in doc["edges"]:
        if e.get("to") in ids:
            e["to"] = ids[e["to"]]
    return doc


def _sites(doc):
    """Per ghost id: the call sites of its unresolved records and of its edges, as (from, file, line, col)."""
    from collections import defaultdict
    rec, edge = defaultdict(set), defaultdict(set)
    for u in doc["unresolved"]:
        if u.get("id"):
            rec[u["id"]].add((u["from"], u["loc"]["file"], u["loc"]["line"], u["loc"]["col"]))
    for e in doc["edges"]:
        if e.get("to") in rec and e.get("loc"):
            edge[e["to"]].add((e["from"], e["loc"]["file"], e["loc"]["line"], e["loc"]["col"]))
    return rec, edge


def test_ghost_families_from_saved_experiment_graph():
    """The real hx/2 orchestrator graph: six `getattr` ghosts from one call site map to one target only because the new
    record carries verified family metadata with the target's scope; `join` + `str.join` map to `str.join` for the
    same reason. Every reference counts (records and edges), every call site must agree, an unchanged id gets no
    shortcut, and a hashed ghost with no family stays ambiguous (review rounds 4-6, 9-11)."""
    old, _ = graphio.load_graph_with_report(ORCH)

    def hx3(i):
        path, _, qual = i.partition("::")
        if path.endswith("builtins.pyi") and qual.split("#")[0] == "getattr":
            return path + "::getattr", {"size": 6, "evidence": "@overload", "scope": "<module>"}
        if path.endswith("builtins.pyi") and qual in ("join", "str.join"):
            return path + "::str.join", {"size": 2, "evidence": "@overload", "scope": "str"}
        return i, None
    new = _rewrite_ghosts(copy.deepcopy(old), hx3)
    getattrs = sorted({u["id"] for u in old["unresolved"] if u["id"].endswith("builtins.pyi::getattr") or "builtins.pyi::getattr#" in u["id"]})
    assert len(getattrs) == 6
    stub = next(u["id"] for u in new["unresolved"] if u["id"].endswith("builtins.pyi::getattr")).rpartition("::")[0]
    frm = "py:src/apragma/backends/build_orchestrator.py::BuildOrchestrator.build"
    lib = "py:/lib/fakelib/__init__.pyi"
    old["unresolved"] += [_ghost("py:src/apragma/x.py::f#deadbeef", frm, 9999),
                          _ghost(lib + "::fetch", frm, 9001), _ghost(lib + "::fetch#11111111", frm, 9002),
                          _ghost(lib + "::fetch2", frm, 9003), _ghost(lib + "::fetch2", frm, 9004),
                          _ghost(lib + "::fetch3", frm, 9005), _ghost(lib + "::fetch3", frm, 9006),
                          _ghost(lib + "::A.fetch", frm, 9007)]
    new["unresolved"] += [_ghost(lib + "::fetch", frm, 9001), _ghost(lib + "::fetch", frm, 9002),
                          _ghost(lib + "::fetch2", frm, 9003), _ghost(lib + "::Cls.fetch2", frm, 9004),   # unchanged id, one site disagrees
                          _ghost(lib + "::fetch3", frm, 9005), _ghost(lib + "::Cls.other", frm, 9006),    # unchanged id, one site incompatible
                          _ghost(lib + "::A.Inner.fetch", frm, 9007)]                                     # added scope without family
    # real ghosts referenced from EDGE-ONLY call sites (the saved graph has 73 such sites)
    rec, edge = _sites(old)
    edge_only = sorted((i, site) for i in rec for site in edge[i] - rec[i] if hx3(i)[0] == i)
    gid, gsite = edge_only[0]
    hid, hsite = next((i, site) for i, site in edge_only if i != gid)
    other = gid.rpartition("::")[0] + "::unrelated_name"
    for e in new["edges"]:                                            # gid's edge-only site now reaches an unrelated name …
        if e.get("to") == gid and e.get("loc") and (e["from"], e["loc"]["file"], e["loc"]["line"], e["loc"]["col"]) == gsite:
            e["to"] = other
    new["unresolved"].append({"name": "unrelated_name", "from": gsite[0], "reason": "outside project root (library)",
                              "loc": {"file": gsite[1], "line": gsite[2], "end_line": gsite[2], "col": gsite[3]}, "id": other})
    new["edges"] = [e for e in new["edges"] if not (e.get("to") == hid and e.get("loc") and             # … and hid's is gone
                                                   (e["from"], e["loc"]["file"], e["loc"]["line"], e["loc"]["col"]) == hsite)]
    node_map = {n: n for n in old["nodes"]}
    mapped, ambiguous, unmapped = project.map_ghost_ids(old, new, node_map)
    assert all(mapped[g] == stub + "::getattr" for g in getattrs)
    assert mapped[stub + "::join"] == stub + "::str.join" and mapped[stub + "::str.join"] == stub + "::str.join"
    assert {u["id"] for u in unmapped} == {"py:src/apragma/x.py::f#deadbeef", lib + "::fetch3", lib + "::A.fetch", gid, hid}
    assert all("call site" in u["reason"] for u in unmapped)
    assert ambiguous == {lib + "::fetch#11111111": [lib + "::fetch"], lib + "::fetch2": [lib + "::Cls.fetch2", lib + "::fetch2"]}
    assert mapped[lib + "::fetch"] == lib + "::fetch" and lib + "::fetch2" not in mapped and lib + "::fetch3" not in mapped
    real = [i for i in rec if hx3(i)[0] == i and i not in (gid, hid) and not i.startswith((lib, "py:src/apragma/x.py::"))]
    assert real and all(mapped.get(i) == i for i in real)                                    # every other real ghost: itself
    # the guard: without the family metadata the many-to-one mappings are refused
    bare = copy.deepcopy(new)
    for u in bare["unresolved"]:
        u.pop("family", None)
    mapped2, ambiguous2, _ = project.map_ghost_ids(old, bare, node_map)
    assert all(g in ambiguous2 for g in getattrs if "#" in g) and stub + "::join" in ambiguous2
    assert mapped2.get(stub + "::join") is None
    # a family whose scope is not the target's scope is no evidence either (round 9)
    wrong = copy.deepcopy(new)
    for u in wrong["unresolved"]:
        if u["id"] == stub + "::str.join":
            u["family"] = {"size": 2, "evidence": "@overload", "scope": "<module>"}
    mapped3, ambiguous3, _ = project.map_ghost_ids(old, wrong, node_map)
    assert ambiguous3.get(stub + "::join") == [stub + "::str.join"] and mapped3.get(stub + "::join") is None
    assert mapped3[stub + "::str.join"] == stub + "::str.join"


def test_nested_function_with_class_scope_maps_from_saved_graphs():
    """Review round 9: in the real graphs `Device._interp_with` (hx/2) is `Device.evaluate._interp_with` (hx/3) at the
    same file, kind and line — an already-qualified old name gains an enclosing-function scope. Nodes only: the
    ghost mapper keeps the strict rule because a ghost has no location anchor of its own."""
    old, _ = graphio.load_graph_with_report(DEVICE)
    with open(DEVICE3, encoding="utf-8") as fh:
        new = json.load(fh)
    assert new["schema"] == "hx/3"   # committed historical fixture, read without upgrade
    mapped, ambiguous, unmapped = project.map_node_ids(old, new, "/root")
    dev = "py:src/apragma/circuit_model/device.py::"
    assert mapped[dev + "Device._interp_with"] == dev + "Device.evaluate._interp_with"
    assert mapped[dev + "Device._is_rgi_axis"] == dev + "Device._interp_pchip_numba._is_rgi_axis"
    assert not ambiguous and not unmapped and len(mapped) == len(old["nodes"]) == 8
    assert project._scope_compatible_node("Device._interp_with", "Device.evaluate._interp_with")
    assert not project._scope_compatible("Device._interp_with", "Device.evaluate._interp_with")
    assert not project._scope_compatible_node("A.x", "B.A.x") and project._scope_compatible_node("x", "outer.x")


def test_invalidated_ids_ignores_id_equality():
    """Review round 9: a module caller keeps its id across hx/2 -> hx/3, so invalidation follows the node's meaning."""
    mid = "py:m.py::(module) m.py"
    old = _doc(nodes={mid: _node(mid, "function", "(module) m.py", "m.py", 1),
                      "py:a.py::f": _node("py:a.py::f", "function", "f", "a.py", 3),
                      "py:a.py::g": _node("py:a.py::g", "function", "g", "a.py", 9)})
    new = _doc(schema="hx/3", nodes={mid: _node(mid, "module", "(module) m.py", "m.py", 1),
                                     "py:a.py::f": _node("py:a.py::f", "function", "f", "a.py", 3),
                                     "py:a.py::C.g": _node("py:a.py::C.g", "method", "g", "a.py", 9)})
    node_map = {mid: mid, "py:a.py::f": "py:a.py::f", "py:a.py::g": "py:a.py::C.g"}
    assert project._invalidated_ids(old, new, node_map) == sorted([mid, "py:a.py::C.g"])


def test_module_verification_is_invalidated_with_an_unchanged_id(tmp_path):
    """Review rounds 9-10: `hxfix/script.py` only imports `dma_poll`, so the tracked entry is the definition with
    callers; the script's module node keeps its hx/2 id, and its verification must still be dropped."""
    if not PYRIGHT:
        pytest.skip("pyright-langserver not installed")
    dst = tmp_path / "python"
    shutil.copytree(FIXPY, dst, ignore=shutil.ignore_patterns(".hx", "__pycache__"))
    root = str(dst)
    project.track(root, "hxfix/dma.py:dma_poll", depth=1, include_callers=True)
    project.update(root)
    gp = project.graph_path(root, "hxfix/dma.py:dma_poll")
    fresh = project.load_graph(gp)
    mid = "py:hxfix/script.py::(module) script.py"
    assert fresh["schema"] == "hx/4" and fresh["nodes"][mid]["kind"] == "module"
    assert sum(1 for n in fresh["nodes"].values() if n["kind"] == "module") == 1
    with open(gp, encoding="utf-8") as fh:
        txt = fh.read()
    with open(gp, "w", encoding="utf-8") as fh:                          # the hx/2 spelling: a function, same id
        fh.write(txt.replace('"kind": "module"', '"kind": "function"').replace('"schema": "hx/4"', '"schema": "hx/2"'))
    A.save(os.path.join(root, ".hx", "annotations.json"),
           {"nodes": {mid: {"verified_body_hash": fresh["nodes"][mid]["body_hash"], "note": "keep"}}})
    out = project.migrate(root)
    assert out["status"] == "migrated" and not out["failed"], out
    assert out["invalidated"] == [mid] and mid not in out["id_map"]
    ann = A.load(os.path.join(root, ".hx", "annotations.json"))
    assert "verified_body_hash" not in ann["nodes"][mid] and ann["nodes"][mid]["note"] == "keep"
    assert ann["meta"]["migrated"]["from"] == "hx/2" and os.path.exists(os.path.join(root, ".hx", "annotations.json.bak-hx2"))


def test_one_to_one_scope_gain_maps_without_family():
    frm = "py:src/x.py::caller"
    old = _doc(nodes={frm: _node(frm, "function", "caller", "src/x.py", 1)},
               unresolved=[_ghost("py:/lib/fakelib/__init__.pyi::only_once", frm, 10, 4)])
    new = _doc(schema="hx/3", nodes={frm: _node(frm, "function", "caller", "src/x.py", 1)},
               unresolved=[_ghost("py:/lib/fakelib/__init__.pyi::Cls.only_once", frm, 10, 4)])
    mapped, ambiguous, unmapped = project.map_ghost_ids(old, new, {frm: frm})
    assert mapped == {"py:/lib/fakelib/__init__.pyi::only_once": "py:/lib/fakelib/__init__.pyi::Cls.only_once"} and not ambiguous and not unmapped
    # a different trailing name, language or declaring path at the same site is never accepted
    for other in ("py:/lib/fakelib/__init__.pyi::Cls.only_twice", "rs:/lib/fakelib/__init__.pyi::Cls.only_once", "py:/lib/other.pyi::Cls.only_once"):
        new2 = _doc(schema="hx/3", nodes=new["nodes"], unresolved=[_ghost(other, frm, 10, 4)])
        m, a, u = project.map_ghost_ids(old, new2, {frm: frm})
        assert not m and not a and [x["id"] for x in u] == ["py:/lib/fakelib/__init__.pyi::only_once"], other


def _legacyize(path, replacements):
    """Rewrite a committed hx/3 graph the way hx/2 would have spelled it, with the given id substitutions."""
    txt = open(path, encoding="utf-8").read()
    for a, b in replacements:
        txt = txt.replace(json.dumps(a)[1:-1], json.dumps(b)[1:-1])
    txt = txt.replace('"schema": "hx/4"', '"schema": "hx/2"')
    open(path, "w", encoding="utf-8").write(txt)
    return txt


def test_migrate_hx2_project_writes_bak_hx2(cproj):
    root = str(cproj)
    project.track(root, "src/main.c:app_run", depth=2)
    project.update(root)
    gp = project.graph_path(root, "src/main.c:app_run")
    fresh = project.load_graph(gp)
    assert fresh["schema"] == "hx/4"
    abs_dma = os.path.realpath(os.path.join(root, "src", "dma.c"))
    old_id, new_id = f"c:{abs_dma}::dma_prog_desc", "c:src/dma.c::dma_prog_desc"
    assert new_id in fresh["nodes"]
    _legacyize(gp, [(new_id, old_id), ('"file": "src/dma.c", "line": ' + str(fresh["nodes"][new_id]["loc"]["line"]),
                                        f'"file": "{abs_dma}", "line": ' + str(fresh["nodes"][new_id]["loc"]["line"]))])
    legacy = project.load_graph(gp)                                   # loader upgrades in memory …
    assert legacy["schema"] == "hx/4" and old_id in legacy["nodes"]   # … but the abs-path id is still the old one
    A.save(os.path.join(root, ".hx", "annotations.json"), {"nodes": {old_id: {"note": "desc"}, "c:src/main.c::app_run": {"note": "keep"}}})
    out = project.migrate(root)
    assert out["status"] == "migrated" and not out["failed"] and not out["ambiguous"], out
    assert out["id_map"][old_id] == new_id
    ann = A.load(os.path.join(root, ".hx", "annotations.json"))
    assert ann["nodes"][new_id]["note"] == "desc" and ann["nodes"]["c:src/main.c::app_run"]["note"] == "keep"
    assert ann["meta"]["migrated"]["from"] == "hx/2" and os.path.exists(os.path.join(root, ".hx", "annotations.json.bak-hx2"))
    assert not os.path.exists(os.path.join(root, ".hx", "annotations.json.bak-hx1"))
    assert project.load_graph(gp)["schema"] == "hx/4" and new_id in project.load_graph(gp)["nodes"]
    assert len(project.list_history(root, "src/main.c:app_run")) >= 1 and out["invalidated"] == []


def test_annotation_migrates_to_the_unique_variant(tmp_path):
    """A note on the hx/2 plain `dup_t` moves to the one variant its user references; with two tracked entries whose
    graphs resolve the plain id to different variants it is listed as ambiguous and left untouched."""
    plain = "c:include/common.h::dup_t"
    # (a) one entry: unique
    proj = _scoped_project(tmp_path, name="one")
    root = str(proj)
    project.track(root, "src/d1.c:d1", depth=3)
    project.update(root)
    gp = project.graph_path(root, "src/d1.c:d1")
    fresh = project.load_graph(gp)
    variant = next(t for t in fresh["types"] if t.startswith(plain + "@"))
    assert fresh["types"][variant]["used_by"] == ["c:src/d1.c::d1"]
    _legacyize(gp, [(variant, plain)])
    A.save(os.path.join(root, ".hx", "annotations.json"), {"types": {plain: {"note": "sep"}}})
    out = project.migrate(root)
    assert out["status"] == "migrated" and out["id_map"][plain] == variant and not out["ambiguous"], out
    ann = A.load(os.path.join(root, ".hx", "annotations.json"))
    assert ann["types"][variant]["note"] == "sep" and plain not in ann["types"]
    # (b) two entries: the same old id maps to different variants -> ambiguous, untouched
    proj2 = _scoped_project(tmp_path, name="two")
    root2 = str(proj2)
    project.track(root2, "src/d1.c:d1", depth=3)
    project.track(root2, "src/d2.c:d2", depth=3)
    project.update(root2)
    variants = []
    for e in ("src/d1.c:d1", "src/d2.c:d2"):
        g = project.load_graph(project.graph_path(root2, e))
        v = next(t for t in g["types"] if t.startswith(plain + "@"))
        variants.append(v)
        _legacyize(project.graph_path(root2, e), [(v, plain)])
    A.save(os.path.join(root2, ".hx", "annotations.json"), {"types": {plain: {"note": "sep"}}})
    out2 = project.migrate(root2)
    assert out2["status"] == "migrated" and out2["ambiguous"].get(plain) == sorted(variants), out2
    assert plain not in out2["id_map"]
    ann2 = A.load(os.path.join(root2, ".hx", "annotations.json"))
    assert ann2["types"][plain]["note"] == "sep" and not any(v in ann2["types"] for v in variants)
