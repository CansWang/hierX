"""Token hashes and the one guard contract."""
import os
import shutil

from hx.api import extract
from hx.netlist import names
from hx.netlist.hashing import statement_hash, scope_hash
from hx.netlist.profiles import NGSPICE

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "spice")


def _proj(tmp_path, sub, name=None):
    dst = tmp_path / (name or sub.replace("/", "_"))
    shutil.copytree(os.path.join(FIX, sub), dst)
    return dst


def test_statement_and_scope_hash_rules():
    assert statement_hash("R1 A B 1K", NGSPICE) == statement_hash("r1   a b 1k", NGSPICE)
    assert statement_hash('v1 a b pwl "x  y"', NGSPICE) != statement_hash('v1 a b pwl "x y"', NGSPICE)    # strings verbatim
    assert statement_hash("r1 a b {w * 2}", NGSPICE) == statement_hash("r1 a b {w*2}", NGSPICE)           # expression spacing is formatting
    assert statement_hash("r1 a b {w*2}", NGSPICE) != statement_hash("r1 a b {w*3}", NGSPICE)
    assert statement_hash("r1 a b 'W * 2'", NGSPICE) == statement_hash("r1 a b 'w*2'", NGSPICE)           # quoted expressions too
    assert statement_hash('r1 a b {x * "ab  cd"}', NGSPICE) != statement_hash('r1 a b {x * "ab cd"}', NGSPICE)   # a string inside stays verbatim
    assert statement_hash(".param a = {b * 2}", NGSPICE) == statement_hash(".param A={B*2}", NGSPICE)
    assert scope_hash(["r1 a b 1k", "c1 a b 1p"], NGSPICE) != scope_hash(["c1 a b 1p", "r1 a b 1k"], NGSPICE)
    assert statement_hash("r1 a b 1k", NGSPICE).startswith("sha1:")


def test_guard_id_ignores_condition_formatting(tmp_path):
    a = extract("cond.sp:.", root=str(_proj(tmp_path, "conditional", "a")), depth=None, dialect="ngspice")
    b = extract("cond_spaced.sp:.", root=str(_proj(tmp_path, "conditional", "b")), depth=None, dialect="ngspice")
    ida = {n.id.split("::", 1)[1] for n in a.nodes.values() if n.kind != "module"}
    idb = {n.id.split("::", 1)[1] for n in b.nodes.values() if n.kind != "module"}
    assert ida == idb and any("#" in i for i in ida)


def test_guard_contract_is_one_representation(tmp_path):
    g = extract("cond.sp:.", root=str(_proj(tmp_path, "conditional")), depth=None, dialect="ngspice")
    f1 = next(n for n in g.nodes.values() if n.name == "f1")
    gid = f1.attrs["guard_id"]
    assert f1.id.endswith("#" + gid) and f1.qualname.endswith("#" + gid)                 # keys, ids and attrs agree
    assert f1.attrs["guard"] == "(pick>0)#0"
    guards = [d["guard"] for rec in g.circuit["models"].values() for d in rec["declarations"] if d["guard_id"]]
    assert guards and all(names.guard_id(names.guard_from_json(gj)) == d["guard_id"]
                          for rec in g.circuit["models"].values() for d in rec["declarations"] for gj in [d["guard"]] if d["guard_id"])


def test_swapping_identical_condition_blocks_keeps_ids(tmp_path):
    a = extract("swap_a.sp:.", root=str(_proj(tmp_path, "conditional", "sa")), depth=None, dialect="ngspice")
    b = extract("swap_b.sp:.", root=str(_proj(tmp_path, "conditional", "sb")), depth=None, dialect="ngspice")
    sa = {n.id.split("::", 1)[1]: n.body_hash for n in a.nodes.values() if n.kind == "device"}
    sb = {n.id.split("::", 1)[1]: n.body_hash for n in b.nodes.values() if n.kind == "device"}
    assert sa == sb and len(sa) == 2 and all("#" in k and "~" not in k for k in sa)


def test_same_name_in_identical_chains_is_a_guarded_duplicate(tmp_path):
    g = extract("dup_chain.sp:.", root=str(_proj(tmp_path, "conditional")), depth=None, dialect="ngspice")
    ra = sorted(n.id.split("::", 1)[1] for n in g.nodes.values() if n.name == "ra")
    assert len(ra) == 2 and ra[0].startswith("ra#") and "~" in ra[1]
    assert any(d["code"] == "guarded-duplicate" for d in g.circuit["diagnostics"])


def test_condition_only_edit_moves_scope_hashes(tmp_path):
    """Changing `.if (pick > 0)` to `(pick > 1)` edits every scope holding that conditional: the deck's and the
    definitions' hashes move (guards are part of the scope hash); spacing inside a condition still does not."""
    a = extract("cond.sp:.", root=str(_proj(tmp_path, "conditional", "a")), depth=None, dialect="ngspice")
    b_root = _proj(tmp_path, "conditional", "b")
    p = b_root / "cond.sp"
    p.write_text(p.read_text().replace("(pick > 0)", "(pick > 1)").replace("(pick>0)", "(pick>1)"))
    b = extract("cond.sp:.", root=str(b_root), depth=None, dialect="ngspice")
    ha = {n.qualname.split("#")[0]: n.body_hash for n in a.nodes.values() if n.kind != "device"}
    hb = {n.qualname.split("#")[0]: n.body_hash for n in b.nodes.values() if n.kind != "device"}
    assert ha["(deck) cond.sp"] != hb["(deck) cond.sp"] and ha["xw"] != hb["xw"] and ha["xw.xl"] != hb["xw.xl"]
    da = {k: {d["hash"] for d in r["declarations"]} for k, r in a.circuit["definitions"].items()}
    db = {k: {d["hash"] for d in r["declarations"]} for k, r in b.circuit["definitions"].items()}
    assert set(da) == set(db) == {"/wrap", "/leaf"} and all(da[k] != db[k] for k in da)
    s = extract("cond_spaced.sp:.", root=str(_proj(tmp_path, "conditional", "c")), depth=None, dialect="ngspice")
    hs = {n.qualname.split("#")[0]: n.body_hash for n in s.nodes.values() if n.kind != "device"}
    assert hs["xw"] == ha["xw"] and hs["(deck) cond_spaced.sp"] == ha["(deck) cond.sp"]
