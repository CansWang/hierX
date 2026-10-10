"""hx/1 -> hx/2: the shared loader on legacy documents, the migration report, annotation key migration and the
staged `hx migrate` operation (CVA6 review, R0)."""
import decimal
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from hx import annotations as A
from hx import graphio, project
from hx.model import Graph

LEGACY = os.path.join(os.path.dirname(__file__), "fixtures", "legacy", "hx1-cva6-like.json")
LEGACY_ANN = os.path.join(os.path.dirname(__file__), "fixtures", "legacy", "hx1-cva6-like.annotations.json")
TOP = "sv:core/top.sv::top"
LANE_OLD = "sv:core/lane.sv::top.gen_lane__BRA__0__KET__.u_lane"
LANE_NEW = "sv:core/lane.sv::top.gen_lane[0].u_lane"


def test_legacy_fixture_has_the_hazards():
    txt = open(LEGACY, encoding="utf-8").read()
    assert re.search(r'"CFG": \d{4300,}', txt) and "__BRA__" in txt and "anon@L29" in txt and '"schema": "hx/1"' in txt
    with pytest.raises(ValueError):
        json.loads(txt)                                   # plain json cannot even parse it under the default limit


def test_loader_upgrades_legacy_in_memory_and_reports():
    doc, rep = graphio.load_graph_with_report(LEGACY)
    assert doc["schema"] == "hx/2" and rep is not None and rep.from_schema == "hx/1"
    assert rep.id_map == {LANE_OLD: LANE_NEW}
    assert LANE_NEW in doc["nodes"] and doc["nodes"][LANE_NEW]["qualname"] == "top.gen_lane[0].u_lane"
    assert doc["nodes"][TOP]["calls"][0] == LANE_NEW and doc["edges"][0]["to"] == LANE_NEW
    cfg = doc["nodes"][TOP]["attrs"]["parameters"]["CFG"]
    assert isinstance(cfg, str) and cfg.startswith("0x") and int(cfg, 16) == (1 << 16384) - 1
    reasons = {x["id"]: x["reason"] for x in rep.needs_reextract}
    assert set(reasons) == {"sv:core/top.sv::anon@L29", "sv:core/fp.sv::struct fp.fp_t"}
    assert "module-scoped" in reasons["sv:core/fp.sv::struct fp.fp_t"] and rep.pending
    assert doc["meta"]["migration"]["needs_reextract_total"] == 2
    g = Graph.load(LEGACY)                                 # the dataclass boundary accepts the upgraded document
    assert g.schema == "hx/2" and LANE_NEW in g.nodes
    with pytest.raises(graphio.SchemaError):
        graphio.upgrade({"schema": "hx/3"})


def _project_with_legacy(tmp_path):
    root = tmp_path / "proj"
    (root / ".hx" / "graphs").mkdir(parents=True)
    name = project.slug("core/top.sv:top")
    shutil.copy(LEGACY, root / ".hx" / "graphs" / f"{name}.json")
    shutil.copy(LEGACY_ANN, root / ".hx" / "annotations.json")
    hist = root / ".hx" / "history" / name
    hist.mkdir(parents=True)
    shutil.copy(LEGACY, hist / "2026-10-09T11-00-00+00-00.json")
    return root, name


def test_every_reader_loads_the_legacy_document(tmp_path):
    from fastapi.testclient import TestClient
    from hx.serve.app import create_app
    from hx.export import build_html
    from hx.mcp_server import GraphStore
    root, name = _project_with_legacy(tmp_path)
    gp = root / ".hx" / "graphs" / f"{name}.json"
    assert project.load_graph(str(gp))["schema"] == "hx/2"
    assert project.find_graphs(str(root))[0]["entry"] == TOP
    assert LANE_NEW in GraphStore(str(root)).load(name)[1]["nodes"]
    html = build_html(project.load_graph(str(gp)), {})
    data = re.search(r'<script type="application/json" id="hx-graph">(.*?)</script>', html, re.S).group(1)
    assert "0x" in data and "Infinity" not in data and "__BRA__" not in data and LANE_NEW in data
    r = subprocess.run([sys.executable, "-m", "hx.cli", "diff", str(gp), str(gp)], capture_output=True, text=True, cwd=str(root))
    assert r.returncode == 0 and "No structural changes" in r.stdout, r.stderr
    app = create_app(str(gp), poll_interval=0.05)
    with TestClient(app) as c:
        g = c.get("/api/graph", params={"name": name}).json()
        assert g["schema"] == "hx/2" and LANE_NEW in g["nodes"] and g["nodes"][TOP]["attrs"]["parameters"]["CFG"].startswith("0x")
        st = c.get("/api/status", params={"name": name}).json()
        assert st["migration"] == "pending" and st["migration_detail"]["needs_reextract_total"] == 2
        assert [x["migration"] for x in c.get("/api/graphs").json()] == ["pending"]
        h = c.get("/api/history", params={"name": name}).json()
        assert len(h["snapshots"]) == 1
        d = c.get("/api/diff", params={"name": name}).json()
        assert d["summary"]["any"] is False
    # loads never write: the files are byte-for-byte as copied
    assert open(gp, "rb").read() == open(LEGACY, "rb").read()
    assert open(root / ".hx" / "annotations.json", "rb").read() == open(LEGACY_ANN, "rb").read()


def test_annotation_key_migration_merges_and_reports():
    doc = {"schema": "hx-ann/1", "nodes": {"old": {"note": "o", "tags": ["a"]}, "new": {"note": "n"}, "keep": {"note": "k"}},
           "types": {}, "globals": {}, "view": {"hidden": ["old"], "pinned_positions": {"old": {"x": 1, "y": 1}}}}
    out, rep = A.migrate_keys(doc, {"old": "new", "other": "x"})
    assert out["nodes"]["new"] == {"note": "n", "tags": ["a"]} and "old" not in out["nodes"] and out["nodes"]["keep"] == {"note": "k"}
    assert rep["renamed"] == 1 and rep["conflicts"] == [{"section": "nodes", "old": "old", "new": "new", "field": "note"}]
    assert out["view"]["hidden"] == ["new"] and out["view"]["pinned_positions"] == {"new": {"x": 1, "y": 1}}
    assert A.normalize({"meta": {"migrated": {"from": "hx/1", "map_hash": "abc", "at": "t"}}})["meta"]["migrated"]["map_hash"] == "abc"
    assert A.normalize({"meta": {"migrated": "junk"}})["meta"] == {}


def test_migrate_file_is_idempotent_with_one_backup(tmp_path):
    p = tmp_path / "annotations.json"
    shutil.copy(LEGACY_ANN, p)
    original = p.read_bytes()
    rep = A.migrate_file(str(p), {LANE_OLD: LANE_NEW})
    assert rep["status"] == "migrated" and rep["renamed"] == 1
    bak = tmp_path / "annotations.json.bak-hx1"
    assert bak.read_bytes() == original
    doc = A.load(str(p))
    assert LANE_NEW in doc["nodes"] and LANE_OLD not in doc["nodes"] and doc["view"]["hidden"] == [LANE_NEW]
    assert doc["meta"]["migrated"]["from"] == "hx/1"
    after_first = p.read_bytes()
    assert A.migrate_file(str(p), {LANE_OLD: LANE_NEW})["status"] == "noop" and p.read_bytes() == after_first and bak.read_bytes() == original
    A.patch_file(str(p), {"nodes": {TOP: {"note": "edited later"}}})         # an ordinary edit keeps the marker
    assert A.load(str(p))["meta"]["migrated"]["map_hash"] == rep["map_hash"]
    assert A.migrate_file(str(p), {LANE_OLD: LANE_NEW})["status"] == "noop" and bak.read_bytes() == original


# ---------------------------------------------------------------- hx migrate on a real (SystemVerilog) project
ADV = os.path.join(os.path.dirname(__file__), "fixtures", "sv_adv")
needs_verilator = pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")


def _legacyize(doc: dict) -> str:
    """Write an hx/2 graph the way hx 0.2.x would have: schema hx/1, module-scoped type ids without the layout suffix
    (so two specializations COLLAPSE onto one id), anonymous ids by line, Verilator spelling, wide values as bare numbers."""
    import copy
    from hx import values as V
    d = copy.deepcopy(doc)
    d["schema"] = "hx/1"
    tmap = {}
    for tid, t in list(d["types"].items()):
        new = tid
        if t.get("anonymous"):
            new = tid.split("::")[0] + "::anon@L" + str((t.get("loc") or {}).get("line") or 1)
        else:
            new = re.sub(r"@[0-9a-f]{8}$", "", tid)
        tmap[tid] = new
    merged = {}
    for tid, t in d["types"].items():
        n = tmap[tid]
        if n in merged:                       # collapse: first layout kept, users merged (what hx/1 did)
            merged[n]["used_by"] = sorted(set(merged[n]["used_by"]) | set(t["used_by"]))
        else:
            t = dict(t, id=n)
            merged[n] = t
    d["types"] = merged
    enc = lambda s: s.replace("[", "__BRA__").replace("]", "__KET__")
    def fix(x):
        if isinstance(x, str):
            x = tmap.get(x, x)
            return enc(x) if x.startswith("sv:") and ("[" in x) else x
        if isinstance(x, list):
            return [fix(v) for v in x]
        if isinstance(x, dict):
            return {enc(k) if k.startswith("sv:") else k: fix(v) for k, v in x.items()}
        return x
    d = fix(d)
    txt = json.dumps(d)
    decimal.getcontext().prec = 20000
    def to_number(m):
        v = V.parse(m.group(1)).int
        return ": " + format(decimal.Decimal(v), "f")
    txt = re.sub(r': "(\d+\'h[0-9a-f]+)"', to_number, txt)     # wide hex strings back to bare decimal numbers
    return txt


def _adv_project(tmp_path, drop_fp64=False):
    root = tmp_path / "advproj"
    shutil.copytree(ADV, root, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
    if drop_fp64:
        top = root / "rtl" / "top_adv.sv"
        top.write_text(top.read_text().replace("  fp #(.E(11), .M(52)) u_fp64 (.clk(clk), .in_bits(f64_i), .out_bits(f64_o));\n", "  assign f64_o = f64_i;\n"))
    project.track(str(root), "rtl/top_adv.sv:top_adv", filelist="files.f", top="top_adv", depth=4, type_depth=3)
    return root


def _tree_hashes(root):
    out = {}
    for base in (".hx/graphs", ".hx/history"):
        for dp, _, fns in os.walk(root / base):
            for fn in fns:
                p = os.path.join(dp, fn)
                out[p] = hashlib.sha1(open(p, "rb").read()).hexdigest()
    ap = root / ".hx" / "annotations.json"
    if ap.exists():
        out[str(ap)] = hashlib.sha1(ap.read_bytes()).hexdigest()
    return out


@needs_verilator
def test_migrate_maps_unique_types_and_yields_an_empty_diff(tmp_path):
    from hx.diff import diff_graphs
    root = _adv_project(tmp_path, drop_fp64=True)
    res = project.update(str(root))
    fresh = res[0].graph
    gp = project.graph_path(str(root), "rtl/top_adv.sv:top_adv")
    legacy_txt = _legacyize(fresh)
    open(gp, "w").write(legacy_txt)
    old_fp = [t for t in json.loads(legacy_txt, parse_int=lambda s: 0)["types"] if "fp.fp_t" in t][0]
    old_anon = [t for t in json.loads(legacy_txt, parse_int=lambda s: 0)["types"] if "anon@L" in t][0]
    A.save(str(root / ".hx" / "annotations.json"), {"types": {old_fp: {"note": "fp"}, old_anon: {"note": "cfg"}},
                                                     "nodes": {"sv:rtl/lane.sv::top_adv.gen_lane__BRA__0__KET__.u_lane": {"note": "lane0"}}})
    # before: the loader reports what it cannot settle
    _, rep = graphio.load_graph_with_report(gp)
    assert {x["id"] for x in rep.needs_reextract} == {old_fp, old_anon}
    out = project.migrate(str(root))
    assert out["status"] == "migrated" and not out["failed"] and not out["ambiguous"] and out["unmapped"] == []
    new_fp = [t for t in fresh["types"] if "fp.fp_t@" in t][0]
    new_anon = [t for t in fresh["types"] if "top_adv.cfg_i@" in t][0]
    assert out["id_map"][old_fp] == new_fp and out["id_map"][old_anon] == new_anon
    assert out["id_map"]["sv:rtl/lane.sv::top_adv.gen_lane__BRA__0__KET__.u_lane"] == "sv:rtl/lane.sv::top_adv.gen_lane[0].u_lane"
    ann = A.load(str(root / ".hx" / "annotations.json"))
    assert ann["types"][new_fp]["note"] == "fp" and ann["types"][new_anon]["note"] == "cfg" and ann["nodes"]["sv:rtl/lane.sv::top_adv.gen_lane[0].u_lane"]["note"] == "lane0"
    assert (root / ".hx" / "annotations.json.bak-hx1").exists()
    # the committed graph is the fresh one; the legacy graph went to history; migrated legacy vs fresh is an empty diff
    assert project.load_graph(gp)["schema"] == "hx/2" and len(project.list_history(str(root), "rtl/top_adv.sv:top_adv")) >= 1
    legacy_doc = graphio.load_graph_text(legacy_txt)
    legacy_doc, _ = graphio.upgrade(legacy_doc)
    legacy_doc = json.loads(json.dumps(legacy_doc).replace(json.dumps(old_fp)[1:-1], json.dumps(new_fp)[1:-1]).replace(old_anon, new_anon))
    d = diff_graphs(legacy_doc, project.load_graph(gp))
    assert d["summary"]["any"] is False, d["summary"]
    # idempotent: run again -> no-op, backup untouched
    before = _tree_hashes(root)
    bak = (root / ".hx" / "annotations.json.bak-hx1").read_bytes()
    out2 = project.migrate(str(root))
    assert out2["annotations"]["status"] in ("noop", None) or out2["annotations"].get("renamed", 0) == 0
    assert (root / ".hx" / "annotations.json.bak-hx1").read_bytes() == bak
    A.patch_file(str(root / ".hx" / "annotations.json"), {"nodes": {"sv:rtl/top_adv.sv::top_adv": {"note": "later"}}})
    out3 = project.migrate(str(root))
    assert (out3["annotations"] or {}).get("renamed", 0) == 0 and (root / ".hx" / "annotations.json.bak-hx1").read_bytes() == bak


@needs_verilator
def test_migrate_leaves_collapsed_types_unmapped(tmp_path):
    root = _adv_project(tmp_path)
    fresh = project.update(str(root))[0].graph
    gp = project.graph_path(str(root), "rtl/top_adv.sv:top_adv")
    open(gp, "w").write(_legacyize(fresh))
    out = project.migrate(str(root))
    assert out["status"] == "migrated"
    um = {u["id"]: u for u in out["unmapped"]}
    assert "sv:rtl/fp.sv::struct fp.fp_t" in um and len(um["sv:rtl/fp.sv::struct fp.fp_t"]["candidates"]) == 2   # never guessed
    assert "sv:rtl/fp.sv::struct fp.fp_t" not in out["id_map"]


@needs_verilator
def test_migrate_writes_nothing_when_an_entry_fails(tmp_path):
    root = _adv_project(tmp_path)
    project.track(str(root), "rtl/lane.sv:top_adv.gen_lane[0].u_lane", filelist="files.f", top="top_adv", depth=1)     # second entry
    project.update(str(root))
    gp = project.graph_path(str(root), "rtl/top_adv.sv:top_adv")
    legacy_txt = _legacyize(project.load_graph(gp))        # read BEFORE opening for write (truncation)
    open(gp, "w").write(legacy_txt)
    A.save(str(root / ".hx" / "annotations.json"), {"nodes": {"sv:rtl/top_adv.sv::top_adv": {"note": "n"}}})
    lane = root / "rtl" / "lane.sv"
    good = lane.read_text()
    lane.write_text(good.replace("endmodule", "endmodul"))          # the SECOND entry's extraction now fails
    before = _tree_hashes(root)
    out = project.migrate(str(root))
    assert out["status"] == "failed" and len(out["failed"]) >= 1
    assert _tree_hashes(root) == before
    assert not (root / ".hx" / "annotations.json.bak-hx1").exists() and not any(d.startswith("staging-") for d in os.listdir(root / ".hx"))
    r = subprocess.run([sys.executable, "-m", "hx.cli", "migrate", "--root", str(root)], capture_output=True, text=True)
    assert r.returncode == 2 and "nothing was written" in r.stderr
    lane.write_text(good)
    r = subprocess.run([sys.executable, "-m", "hx.cli", "migrate", "--root", str(root)], capture_output=True, text=True)
    assert r.returncode == 0 and "status      migrated" in r.stdout, r.stdout + r.stderr
    assert project.load_graph(gp)["schema"] == "hx/2" and (root / ".hx" / "annotations.json.bak-hx1").exists()
