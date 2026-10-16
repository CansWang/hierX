"""The ngspice oracle: rendered closure, listing parser, name forms, projection, arity, references; live agreement."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from hx.netlist import oracle
from hx.netlist.index import DesignIndex
from hx.netlist.profiles import NGSPICE, SPICE_FAMILIES
from hx.tools import resolve_tool
from hx.frontends.base import FrontendError

sys.path.insert(0, os.path.dirname(__file__))
from conftest import require_tool  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "spice")

PROBE_LISTING = """Circuit: probe deck
\tprobe deck
     1 : probe deck
    20 : .model dmod d is=1e-14
    11 : .model xa:dmod d is=2e-14
     9 : c.xa.c.xh.c1 n1 n2 1p 
    13 : d.xa.d1 n1 n2 xa:dmod 
     5 : r.xb.xh.r1 n2 n3 1k
    18 : r.xb.r2 n2 n3   5.000000000000000e+03   
    23 : q1 n3 n1 0 0 npnmod
    24 : q2 n3 n1 0 npnmod
    25 : f1 n1 0 vs 2
    26 : vs n2 0 1
    27 : k1 l1 l2 0.5
    28 : l1 n1 0 1u
    29 : l2 n3 0 1u
    31 : ropt n1 n3 10k
    35 : .model npnmod npn bf=100
    32 : .end
ngspice-45.2 done
"""


def _dev(name, letter, terminals, segments=(), flags=(), model=None, prefix=None, refs=(), guarded=False, family=None):
    return oracle.HxDevice(node_id="sp:x::" + name, letter=letter, name=name, segments=list(segments), local_flags=list(flags),
                           guarded=guarded, terminals=list(terminals), model=model, model_scope_prefix=prefix, refs=list(refs),
                           family=family or SPICE_FAMILIES[letter])


def test_title_row_is_not_a_device_and_models_sit_anywhere():
    lst = oracle.parse_listing(PROBE_LISTING)
    assert lst.title == "probe deck" and sorted(lst.models) == ["dmod", "npnmod", "xa:dmod"]
    assert [r.tokens[0] for r in lst.devices] == ["c.xa.c.xh.c1", "d.xa.d1", "r.xb.xh.r1", "r.xb.r2", "q1", "q2", "f1", "vs", "k1", "l1", "l2", "ropt"]
    dot = oracle.parse_listing("     1 : .subckt fake a b\n     3 : r1 n1 0 1k\n")
    assert dot.title == ".subckt fake a b" and [r.tokens[0] for r in dot.devices] == ["r1"]


def test_name_forms_by_declaration_context():
    assert oracle.ngspice_name("c", ["xa", "xh"], [False, True], "c1") == "c.xa.c.xh.c1"
    assert oracle.ngspice_name("r", ["xb", "xh"], [False, False], "r1") == "r.xb.xh.r1"
    assert oracle.ngspice_name("r", ["xo", "xm", "xg", "xl"], [False, False, False, True], "r1") == "r.xo.xm.xg.r.xl.r1"
    assert oracle.ngspice_name("q", [], [], "Q1") == "q1"
    assert oracle.strip_letters("r.xo.xm.xg.r.xl.r1") == (["xo", "xm", "xg", "xl"], "r1")


def test_projection_arity_models_refs_and_numeric_nets():
    lst = oracle.parse_listing(PROBE_LISTING)
    devs = [_dev("c1", "C", ["n1", "n2"], ["xa", "xh"], [False, True]),
            _dev("d1", "D", ["n1", "n2"], ["xa"], [False], model="dmod", prefix="xa"),
            _dev("r1", "R", ["n2", "n3"], ["xb", "xh"], [False, False]),
            _dev("r2", "R", ["n2", "n3"], ["xb"], [False]),
            _dev("q1", "Q", ["n3", "n1", "0", "0"], model="npnmod", prefix=""),
            _dev("q2", "Q", ["n3", "n1", "0"], model="npnmod", prefix=""),
            _dev("f1", "F", ["n1", "0"], refs=["vs"]), _dev("vs", "V", ["n2", "0"]),
            _dev("k1", "K", [], refs=["l1", "l2"]), _dev("l1", "L", ["n1", "0"]), _dev("l2", "L", ["n3", "0"]),
            _dev("ropt", "R", ["n1", "n3"], guarded=True), _dev("ropt", "R", ["n1", "n3"], guarded=True)]
    res = oracle.compare(devs, lst, NGSPICE, {"dmod", "npnmod"})
    assert res["mismatches"] == [] and res["summary"]["compared"] == 11 and res["summary"]["guarded_hx"] == 2 and res["summary"]["guarded_sim"] == 1
    # a frontend that dropped a resistor terminal is caught by the listing's family grammar, not trusted
    bad = oracle.compare([_dev("r2", "R", ["n2"], ["xb"], [False])], lst, NGSPICE, set())
    assert [m["what"] for m in bad["mismatches"] if m["path"] == "r.xb.r2"][0] == "arity"
    # numeric net names are terminals; a bin family name is a model token
    num = oracle.parse_listing("     1 : t\n     3 : q1 1 2 3 0 qm\n     4 : m1 1 2 3 4 nfet_03v3 w=1u l=1u\n     9 : .model qm npn bf=50\n")
    ok = oracle.compare([_dev("q1", "Q", ["1", "2", "3", "0"], model="qm", prefix=""), _dev("m1", "M", ["1", "2", "3", "4"], model="nfet_03v3", prefix="")],
                        num, NGSPICE, {"nfet_03v3"})
    assert ok["mismatches"] == [] and ok["summary"]["compared"] == 2
    # a wrong model scope and a wrong reference are reported
    wrong = oracle.compare([_dev("d1", "D", ["n1", "n2"], ["xa"], [False], model="dmod", prefix=""), _dev("f1", "F", ["n1", "0"], refs=["vx"])], lst, NGSPICE, {"dmod"})
    assert sorted(m["what"] for m in wrong["mismatches"] if m["what"] in ("model", "ref")) == ["model", "ref"]


def test_guarded_simulator_rows_are_excluded_and_subtree_scope():
    lst = oracle.parse_listing(PROBE_LISTING)
    only_guarded = oracle.compare([_dev("ropt", "R", ["n1", "n3"], guarded=True)], lst, NGSPICE, set())
    assert not any(m["path"] == "ropt" for m in only_guarded["mismatches"]) and only_guarded["summary"]["guarded_sim"] == 1
    sub = oracle.compare([_dev("c1", "C", ["n1", "n2"], ["xa", "xh"], [False, True]), _dev("d1", "D", ["n1", "n2"], ["xa"], [False], model="dmod", prefix="xa")],
                         lst, NGSPICE, {"dmod"}, subtree=["xa"])
    assert sub["mismatches"] == [] and sub["summary"]["out_of_scope"] == 10


def _index(deck, search_paths=()):
    return DesignIndex(deck, NGSPICE, "ngspice", list(search_paths), os.path.dirname(deck), None).build()


def test_oracle_input_reproduces_search_path_includes_and_strips_control_blocks():
    deck = os.path.join(FIX, "oracle", "search_path", "deck.sp")
    render = oracle.render_closure(_index(deck, ["inc"]))
    assert ".subckt shared a b" in render and "r1 a b 1k" in render and "r_inc n1 0 2k" in render     # includes inlined
    assert "echo" not in render and "oracle_side_effect" not in render                                # .control inside an include stripped
    assert render.rstrip().endswith(".control\nlisting expand\nquit\n.endc\n.end")
    ota = oracle.render_closure(_index(os.path.join(FIX, "ota", "ota.sp")))
    assert ".model nch nmos" in ota and ".model pch_hv" in ota and "vto=0.3 kp=240u" not in ota        # tt selected, ff not
    assert "wrdata" not in ota and ".ac dec" not in ota and ".op" not in ota.split("\n")               # no analyses, no control
    assert ".if (vdd_val > 1.5)" in ota and ".else" in ota and ".endif" in ota


def test_missing_tool_is_named():
    with pytest.raises(FrontendError) as ei:
        resolve_tool("ngspice", "/nonexistent/ngspice")
    assert "ngspice executable '/nonexistent/ngspice' not found" in str(ei.value) and "apt-get install -y ngspice" in str(ei.value) and "--ngspice PATH" in str(ei.value)
    r = subprocess.run([sys.executable, "-m", "hx.cli", "netlist", "check", "ota.sp:.", "--oracle", "ngspice", "--ngspice", "/nonexistent/ngspice"],
                       cwd=os.path.join(FIX, "ota"), capture_output=True, text=True)
    assert r.returncode == 2 and "ngspice executable" in r.stderr and "install it" in r.stderr


def _run_check(args, cwd):
    return subprocess.run([sys.executable, "-m", "hx.cli", "netlist", "check", *args], cwd=cwd, capture_output=True, text=True)


def test_live_agreement(tmp_path):
    require_tool("ngspice")
    for sub in ("ota", "scoped", "oracle/search_path", "bjt", "numeric_nets", "globals", "pdk", "switches", "conditional", "params"):
        shutil.copytree(os.path.join(FIX, sub), tmp_path / sub.replace("/", "_"))
    r = _run_check(["ota_oracle.sp:.", "--json"], tmp_path / "ota")
    rep = json.loads(r.stdout)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert rep["status"] == "agree" and rep["summary"]["compared"] >= 20 and rep["summary"]["guarded_hx"] == 0, rep["summary"]
    r = _run_check(["ota.sp:.", "--json"], tmp_path / "ota")
    rep = json.loads(r.stdout)
    assert rep["status"] == "agree" and rep["summary"]["guarded_hx"] == 2 and rep["summary"]["guarded_sim"] == 1, rep["summary"]
    r = _run_check(["ota.sp:xa", "--json"], tmp_path / "ota")
    rep = json.loads(r.stdout)
    assert rep["status"] == "agree" and rep["summary"]["out_of_scope"] > 0 and rep["summary"]["compared"] > 0, rep["summary"]
    r = _run_check(["mixed.sp:."], tmp_path / "scoped")
    assert r.returncode == 0 and "status      agree" in r.stdout, r.stdout + r.stderr
    r = _run_check(["scoped.sp:."], tmp_path / "scoped")
    assert r.returncode == 0, r.stdout + r.stderr
    r = _run_check(["deck.sp:.", "--search-path", "inc", "--json"], tmp_path / "oracle_search_path")
    rep = json.loads(r.stdout)
    assert rep["status"] == "agree" and not os.path.exists(tmp_path / "oracle_search_path" / "oracle_side_effect.txt"), rep.get("reason")
    for sub, deck in (("bjt", "bjt.sp"), ("numeric_nets", "numeric.sp"), ("globals", "globals.sp"), ("pdk", "pdk.sp")):
        r = _run_check([f"{deck}:."], tmp_path / sub)
        assert r.returncode == 0, (sub, r.stdout + r.stderr)
    r = _run_check(["switches.sp:.", "--json"], tmp_path / "switches")
    rep = json.loads(r.stdout)
    assert rep["status"] == "agree" and rep["summary"]["compared"] == 11, rep                          # w1/s1 compared with their models
    r = _run_check(["ref_alternatives.sp:.", "--json"], tmp_path / "conditional")
    rep = json.loads(r.stdout)
    assert rep["status"] == "agree" and rep["summary"]["compared"] == 9 and rep["summary"]["guarded_hx"] == 4 and rep["summary"]["guarded_sim"] == 2, rep["summary"]
    # definition-rooted entries with deck context: one comparison per unguarded instance, nothing outside leaks in
    r = _run_check(["lib/devices.inc:@cm", "--deck", "ota.sp", "--json"], tmp_path / "ota")
    rep = json.loads(r.stdout)
    assert r.returncode == 0 and rep["status"] == "agree" and {i["path"] for i in rep["instances"]} == {"xa.x_cm", "xb.x_cm"}, rep.get("reason")
    assert rep["summary"]["instances"] == 2 and rep["summary"]["mismatches"] == 0 and rep["summary"]["compared"] > 0 and rep["summary"]["out_of_scope_hx"] > 0
    r = _run_check(["ota.sp:@five_t_opamp", "--json"], tmp_path / "ota")                          # the entry file is itself the deck
    rep = json.loads(r.stdout)
    assert rep["status"] == "agree" and {i["path"] for i in rep["instances"]} == {"xa", "xb"} and rep["summary"]["guarded_instances"] == 0, rep.get("reason")
    r = _run_check(["ota.sp:@five_t_opamp"], tmp_path / "ota")
    assert r.returncode == 0 and "instance    xa:" in r.stdout and "instances 2" in r.stdout, r.stdout
    r = _run_check(["inc_first_subckt.inc:@leaf"], tmp_path / "params")                             # a standalone library: no deck
    assert r.returncode == 2 and "no deck context" in r.stdout and "--deck" in r.stdout


def test_subtree_filters_both_sides():
    """An instance-path comparison restricts hx's devices as well as the listing rows: a sibling instance and a
    top-level device are out of scope on both sides, never `missing-in-ngspice`."""
    lst = oracle.parse_listing("     1 : t\n     3 : r.xa.r1 n1 0 1k\n     4 : r.xb.r1 n1 0 1k\n     5 : rtop n1 0 1k\n")
    devs = [_dev("r1", "R", ["n1", "0"], ["xa"], [False]), _dev("r1", "R", ["n1", "0"], ["xb"], [False]), _dev("rtop", "R", ["n1", "0"]),
            _dev("rg", "R", ["n1", "0"], ["xb"], [False], guarded=True)]
    res = oracle.compare(devs, lst, NGSPICE, set(), subtree=["xa"])
    s = res["summary"]
    assert res["mismatches"] == [] and (s["compared"], s["out_of_scope"], s["out_of_scope_hx"], s["guarded_hx"]) == (1, 2, 3, 0)
    whole = oracle.compare(devs, lst, NGSPICE, set())
    assert whole["mismatches"] == [] and whole["summary"]["compared"] == 3 and whole["summary"]["out_of_scope_hx"] == 0


def test_required_model_missing_in_hx_never_agrees():
    """A family that needs a model is always compared: hx reporting no model for `w1 out 0 vsense sm` is a `model`
    mismatch, not a skipped comparison (the switch grammar bug passed the oracle this way)."""
    lst = oracle.parse_listing("     1 : t\n     2 : vsense n2 0 1\n     3 : w1 out 0 vsense sm\n     4 : .model sm csw it=0.5\n")
    res = oracle.compare([_dev("w1", "W", ["out", "0"], refs=["vsense"], model=None), _dev("vsense", "V", ["n2", "0"])], lst, NGSPICE, set())
    assert [(m["what"], m["hx"], m["ngspice"]) for m in res["mismatches"]] == [("model", None, "sm")]
    ok = oracle.compare([_dev("w1", "W", ["out", "0"], refs=["vsense"], model="sm", prefix=""), _dev("vsense", "V", ["n2", "0"])], lst, NGSPICE, set())
    assert ok["mismatches"] == [] and ok["summary"]["compared"] == 2
    bare = oracle.parse_listing("     1 : t\n     3 : w1 out 0 vsense\n")                       # a listing row without a model cannot agree either
    assert [m["what"] for m in oracle.compare([_dev("w1", "W", ["out", "0"], refs=["vsense"], model="sm", prefix="")], bare, NGSPICE, {"sm"})["mismatches"]] == ["model"]


def test_hx_devices_fall_back_to_as_written_for_missing_references(tmp_path):
    from hx.api import extract
    from hx.netlist import check
    shutil.copytree(os.path.join(FIX, "fail"), tmp_path / "fail")
    g = extract("ref_duplicate_and_missing.sp:.", root=str(tmp_path / "fail"), depth=None, dialect="ngspice")
    fe = check._frontend_for(g, str(tmp_path / "fail"), "ngspice", [])
    devs = {d.name: d for d in check._hx_devices(g, fe)}
    assert devs["fx"].refs == ["vnone"] and devs["f2"].refs == ["vdup"]
    assert any(d["code"] == "ambiguous-reference" for d in g.circuit["diagnostics"]) and any(u.id.endswith("vnone?") for u in g.unresolved)


def test_definition_check_without_usable_instances(tmp_path):
    """A definition with no unguarded instance in the deck is `unavailable` (exit 2) before the simulator starts."""
    from hx.netlist.check import check_ngspice
    for sub in ("oracle", "conditional"):
        shutil.copytree(os.path.join(FIX, sub), tmp_path / sub)
    rep = check_ngspice("uninstantiated.sp:@unused", root=str(tmp_path / "oracle"), exe=sys.executable)     # resolved, never run
    assert rep["status"] == "unavailable" and "no unguarded instance" in rep["reason"] and rep["summary"] == {"instances": 0, "guarded_instances": 0}
    assert rep["render"] is None and "uninstantiated.sp" in rep["reason"] and "'unused'" in rep["reason"]
    rep = check_ngspice("nested_guard.sp:@leaf", root=str(tmp_path / "conditional"), exe=sys.executable, deck="nested_guard.sp")
    assert rep["status"] == "unavailable" and rep["summary"] == {"instances": 0, "guarded_instances": 4} and "4 guarded" in rep["reason"]
    r = _run_check(["uninstantiated.sp:@unused", "--ngspice", sys.executable], tmp_path / "oracle")
    assert r.returncode == 2 and "no unguarded instance" in r.stdout
