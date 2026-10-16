"""Elaborator: occurrences under guards, nets and bindings, references, arity, recursion, missing things."""
import os

from hx.netlist.index import DesignIndex
from hx.netlist.names import guard_text
from hx.netlist.profiles import NGSPICE
from hx.netlist.resolve import Elaborator

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "spice")


def _elab(*parts, search_paths=()):
    deck = os.path.join(FIX, *parts)
    idx = DesignIndex(deck, NGSPICE, "ngspice", list(search_paths), os.path.dirname(deck), None).build()
    return Elaborator(idx)


def _all(el, occ=None, out=None):
    out = [] if out is None else out
    for c in el.children(occ or el.root):
        out.append(c)
        if c.kind == "inst":
            _all(el, c, out)
    return out


def test_guarded_occurrences_have_distinct_keys_bindings_and_refs():
    el = _elab("conditional", "cond.sp")
    occs = {o.key: o for o in _all(el)}
    xl = [o for o in occs.values() if o.path == ("xw", "xl")]
    assert len(xl) == 2 and len({o.gid for o in xl}) == 2 and all(o.kind == "inst" for o in xl)
    recs = {o.gid: el.instance(o) for o in xl}
    outs = {gid: [b["outer"] for b in r.bindings] for gid, r in recs.items()}
    assert sorted(outs.values()) == [["xw.in", "xw.out"], ["xw.out", "xw.in"]]           # swapped per branch
    inner = el.nets["xw.xl.a"]
    assert len(inner.bindings) == 2 and {b["via"] for b in inner.bindings} == {o.key for o in xl}
    r1 = [o for o in occs.values() if o.path == ("xw", "xl", "r1")]
    assert len(r1) == 4 and len({o.gid for o in r1}) == 4                                 # 2 wrap branches × 2 leaf branches
    assert all(len(o.guard) == 2 for o in r1)                                             # the child inherits the parent's constraints
    f1 = next(o for o in occs.values() if o.path == ("f1",))
    rec = el.device(f1)
    assert f1.gid and [t.path for t in rec.refs[0]["targets"]] == [("vsense",)] and not rec.refs[0]["targets"][0].gid   # a guarded ref sees an unconditional V
    d1 = el.device(next(o for o in occs.values() if o.path == ("d1",)))
    assert d1.model_status == "alternatives" and len(d1.model_refs) == 3


def test_bjt_arity_and_numeric_nets():
    el = _elab("bjt", "bjt.sp")
    q = {o.path[-1]: el.device(o) for o in _all(el) if o.element.letter == "Q"}
    assert [t["terminal"] for t in q["q1"].terminals] == ["c", "b", "e", "s"] and [t["terminal"] for t in q["q2"].terminals] == ["c", "b", "e"]
    assert q["q1"].model_status == "found" and not q["q1"].diagnostics
    el2 = _elab("numeric_nets", "numeric.sp")
    d = {o.path[-1]: el2.device(o) for o in _all(el2)}
    assert [t["net"] for t in d["q1"].terminals] == ["1", "2", "3", "0"] and d["q1"].parts.master == "qm"
    assert [t["net"] for t in d["m1"].terminals] == ["1", "2", "3", "4"] and d["r1"].parts.value == "1k"


def test_recursion_wrong_terminals_missing_model_unknown_family():
    el = _elab("fail", "recursive.sp")
    occs = {o.path: o for o in _all(el)}
    assert occs[("xs", "x1")].recursive and occs[("xm", "x1", "x1")].recursive and ("xm", "x1", "x1", "x1") not in occs
    chain = [x["code"] for x in el.instance(occs[("xm", "x1", "x1")]).diagnostics]
    assert chain == ["recursive-hierarchy"]
    el = _elab("fail", "wrong_terminals.sp")
    occs = {o.path[-1]: o for o in _all(el)}
    x1, x2, m1 = el.instance(occs["x1"]), el.instance(occs["x2"]), el.device(occs["m1"])
    assert x1.extra == ["n3"] and x2.unbound == ["b"] and [d["code"] for d in m1.diagnostics] == ["terminal-count-mismatch"]
    el = _elab("fail", "missing_model.sp")
    occs = {o.path[-1]: o for o in _all(el)}
    assert el.device(occs["d1"]).model_status == "missing" and el.device(occs["m1"]).model_status == "missing"
    el = _elab("fail", "unsupported.sp")
    occs = {o.path[-1]: o for o in _all(el)}
    assert el.device(occs["y1"]).family is None and [d["code"] for d in el.device(occs["y1"]).diagnostics] == ["unknown-device-family"]
    assert el.device(occs["r1"]).parts.value == "1k"


def test_bins_and_scoped_models():
    el = _elab("bins", "bins.sp")
    m1 = next(o for o in _all(el) if o.path == ("xmn", "m1"))
    rec = el.device(m1)
    assert rec.model_status == "binned" and [m["key"] for m in rec.model_refs] == ["/nm.0", "/nm.1", "/nm.2"]
    el = _elab("scoped", "scoped.sp")
    occs = {o.path: o for o in _all(el)}
    assert el.device(occs[("xa", "d1")]).model_refs == [{"guard_id": "", "key": "outer_a/dmod"}]
    assert el.device(occs[("d0",)]).model_refs == [{"guard_id": "", "key": "/dmod"}]
    assert occs[("xa", "xh")].decl.scope == ("outer_a",) and occs[("xb", "xh")].decl.scope == ()


def test_globals_ground_and_three_level_bindings():
    el = _elab("globals", "globals.sp")
    occs = {o.path: o for o in _all(el)}
    r1 = el.device(occs[("x_top", "x_mid", "x_in", "r1")])
    r2 = el.device(occs[("x_top", "x_mid", "x_in", "r2")])
    assert [t["net"] for t in r1.terminals] == ["x_top.x_mid.x_in.a", "vdd"] and [t["net"] for t in r2.terminals] == ["x_top.x_mid.x_in.b", "0"]
    assert el.canonical("x_top.x_mid.x_in.a") == "in" and el.canonical("x_top.x_mid.x_in.b") == "out"
    assert el.nets["vdd"].kind == "global" and el.nets["0"].kind == "ground"
    f1 = el.device(occs[("f1",)])
    assert [t.path for t in f1.refs[0]["targets"]] == [("vs",)]


def test_guarded_duplicate_gets_a_suffix():
    el = _elab("conditional", "dup_chain.sp")
    ra = [o for o in _all(el) if o.path == ("ra",)]
    assert len(ra) == 2 and ra[0].gid == ra[1].gid and ra[0].dup_suffix == "" and ra[1].dup_suffix.startswith("~")
    assert [d["code"] for d in el.diagnostics] == ["guarded-duplicate"]
    assert guard_text(ra[0].guard) == "(pick>0)#0"


def test_nested_guarded_bindings_follow_the_ancestor_chain():
    """Two guarded `xw` occurrences bind `xw.in` to n1 and n2; each nested `xw.xl` variant must follow its own
    ancestor's binding (the first binding is never a fallback)."""
    el = _elab("conditional", "nested_guard.sp")
    r1s = [o for o in _all(el) if o.path == ("xw", "xl", "r1")]
    assert len(r1s) == 4
    got = {}
    for o in r1s:
        rec = el.device(o)
        branch = dict(o.guard)
        top = next(c for c in branch if c.startswith("|"))
        wrap = next(c for c in branch if c.startswith("wrap|"))
        got[(branch[top], branch[wrap])] = (el.canonical(rec.terminals[0]["net"], o), el.canonical(rec.terminals[1]["net"], o))
    assert got == {(0, 0): ("n1", "n2"), (0, 1): ("n2", "n1"), (1, 0): ("n2", "n1"), (1, 1): ("n1", "n2")}
    assert {b["outer"] for b in el.nets["xw.in"].bindings} == {"n1", "n2"}
    assert el.canonical("xw.in") == "xw.in"                     # two bindings and no chain: nothing is guessed
    xl = next(o for o in _all(el) if o.path == ("xw", "xl"))
    assert el.canonical("xw.xl.a", xl) == el.canonical(el.instance(xl).bindings[0]["outer"], xl) in ("n1", "n2")


def test_unconditional_reference_keeps_guarded_alternatives():
    el = _elab("conditional", "ref_alternatives.sp")
    occs = list(_all(el))
    f1 = el.device(next(o for o in occs if o.path == ("f1",)))
    ts = f1.refs[0]["targets"]
    assert [t.path for t in ts] == [("vs",), ("vs",)] and len({t.gid for t in ts}) == 2 and all(t.gid for t in ts) and f1.diagnostics == []
    h1 = el.device(next(o for o in occs if o.path == ("h1",)))
    assert len(h1.refs[0]["targets"]) == 2
    k1 = el.device(next(o for o in occs if o.path == ("k1",)))
    assert [len(r["targets"]) for r in k1.refs] == [1, 2] and k1.diagnostics == []


def test_duplicate_and_missing_reference_targets():
    el = _elab("fail", "ref_duplicate_and_missing.sp")
    occs = list(_all(el))
    f2 = el.device(next(o for o in occs if o.path == ("f2",)))
    ts = f2.refs[0]["targets"]
    assert len(ts) == 2 and len({t.key for t in ts}) == 2 and sum(1 for t in ts if t.dup_suffix) == 1
    assert [d["code"] for d in f2.diagnostics] == ["ambiguous-reference"] and any(d["code"] == "guarded-duplicate" for d in el.diagnostics)
    fx = el.device(next(o for o in occs if o.path == ("fx",)))
    assert fx.refs[0]["targets"] == [] and [d["code"] for d in fx.diagnostics] == ["missing-reference"] and "vnone" in fx.refs[0]["reason"]
