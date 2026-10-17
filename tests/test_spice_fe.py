"""SPICE frontend end to end: entries, callers, ids, the circuit block, unresolved reasons, caching."""
import json
import os
import shutil
import time

import pytest

from hx.api import extract
from hx.frontends.base import EntryNotFound
from hx.frontends.spice_fe import SpiceFrontend

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "spice")


def _proj(tmp_path, sub, name=None):
    dst = tmp_path / (name or sub.replace("/", "_"))
    shutil.copytree(os.path.join(FIX, sub), dst, ignore=shutil.ignore_patterns(".hx"))
    return dst


def _ids(g):
    return {n.id for n in g.nodes.values()}


def test_whole_deck_graph_and_circuit_block(tmp_path):
    proj = _proj(tmp_path, "ota")
    g = extract("ota.sp:.", root=str(proj), depth=None, dialect="ngspice")
    assert g.entry == "sp:ota.sp::(deck) ota.sp" and g.lang == "sp" and g.schema == "hx/4"
    kinds = {n.kind for n in g.nodes.values()}
    assert kinds == {"module", "instance", "device"} and all(n.precision == "syntax" for n in g.nodes.values())
    assert "sp:ota.sp::xa.x_cm.xref.m1" in g.nodes and "sp:ota.sp::xa.xm_in1.m1" in g.nodes
    xa = g.nodes["sp:ota.sp::xa"]
    assert xa.signature == "five_t_opamp XA (vip vin outa ibias vdd 0)" and [p.name for p in xa.params] == ["vip", "vin", "vout", "ibias", "vdd", "vss"]
    assert xa.attrs["definition_file"] == "ota.sp" and xa.body_hash == g.nodes["sp:ota.sp::xb"].body_hash
    m = g.nodes["sp:ota.sp::xa.m_load_1"]
    assert m.attrs["model"] == "pch" and m.attrs["parameters"] == {"w": "4u", "l": "0.18u"} and [p.name for p in m.params] == ["d", "g", "s", "b"]
    c = g.circuit
    assert c["dialect"] == "ngspice" and c["root"] == {"kind": "deck", "id": g.entry, "deck_role": "deck"}
    assert [f["role"] for f in c["files"]] == ["deck", "include", "lib", "include"] and c["files"][2]["section"] == "tt"
    assert c["terminals"][m.id] == [{"terminal": "d", "net": "xa.vmir", "canonical": "xa.vmir", "as_written": "vmir"}, {"terminal": "g", "net": "xa.vmir", "canonical": "xa.vmir", "as_written": "vmir"},
                                    {"terminal": "s", "net": "vdd", "canonical": "vdd", "as_written": "vdd"}, {"terminal": "b", "net": "vdd", "canonical": "vdd", "as_written": "vdd"}]
    assert c["ports"][xa.id][0] == {"port": "vip", "inner": "xa.vip", "outer": "vip", "net": "vip", "as_written": "vip"}
    assert c["nets"]["xa.vip"]["kind"] == "port" and c["nets"]["xa.vip"]["bindings"][0]["canonical"] == "vip"
    assert c["nets"]["vdd"]["kind"] == "global" and c["nets"]["0"]["kind"] == "ground"
    assert c["definitions"]["/five_t_opamp"]["instances"] == ["sp:ota.sp::xa", "sp:ota.sp::xb"]
    assert c["definitions"]["cm/mirror_leg"]["declarations"][0]["id"] == "sp:lib/devices.inc::@cm/mirror_leg"
    assert c["models"]["/pch"]["status"] == "found" and m.id in c["models"]["/pch"]["used_by"] and c["models"]["/pch"]["declarations"][0]["file"] == "lib/tt_models.inc"
    assert c["params"]["/vdd_val"]["declarations"][0]["expr"] == "1.8"
    assert [d["name"] for d in c["directives"]] == [".op", ".ac", ".end"] and len(c["control_blocks"]) == 1 and "wrdata" in c["control_blocks"][0]["text"]
    assert c["diagnostics"] == [] and g.meta["deps"] == ["lib/corners.lib", "lib/devices.inc", "lib/tt_models.inc", "ota.sp"]
    assert "sp:ota.sp::net vdd" in g.globals and "sp:ota.sp::net vdd" in g.nodes["sp:ota.sp::xa.m_load_1"].globals.reads
    f1 = g.nodes["sp:ota.sp::f1"]
    assert f1.attrs["controls"] == [{"role": "vsource", "as_written": "VSENSE", "targets": ["sp:ota.sp::vsense"]}]
    assert any(e.src == f1.id and e.dst == "sp:ota.sp::vsense" and e.kind == "ref" for e in g.edges)
    k1 = g.nodes["sp:ota.sp::k1"]
    assert [x["targets"] for x in k1.attrs["controls"]] == [["sp:ota.sp::l1"], ["sp:ota.sp::l2"]] and k1.params == []
    ropt = sorted(n.id for n in g.nodes.values() if n.name == "R_opt")
    assert len(ropt) == 2 and all("#" in r for r in ropt)
    assert g.unresolved == [] and g.meta["index"]["dialect"] == "ngspice" and g.meta["index"]["files"] == 4


def test_entry_forms_and_errors(tmp_path):
    proj = _proj(tmp_path, "ota")
    g = extract("ota.sp:xa.x_cm", root=str(proj), depth=2, include_callers=True, dialect="ngspice")
    assert g.entry == "sp:ota.sp::xa.x_cm" and g.nodes["sp:ota.sp::xa"].depth == -1 and g.nodes["sp:ota.sp::(deck) ota.sp"].depth == -2
    assert g.nodes["sp:ota.sp::xa.x_cm.xref"].depth == 1 and g.nodes["sp:ota.sp::xa.x_cm.xref.m1"].depth == 2
    g1 = extract("ota.sp:xa", root=str(proj), depth=1, dialect="ngspice")
    assert any(u.reason == "beyond depth limit" for u in g1.unresolved)
    g = extract("lib/devices.inc:@cm", root=str(proj), depth=None, dialect="ngspice", deck="ota.sp")
    assert g.entry == "sp:lib/devices.inc::@cm" and "sp:lib/devices.inc::@cm.xref.m1" in g.nodes and g.circuit["root"]["kind"] == "definition"
    g = extract("lib/devices.inc:@cm/mirror_leg", root=str(proj), depth=None, deck="ota.sp")
    assert g.entry == "sp:lib/devices.inc::@cm/mirror_leg"
    g = extract("ota.sp:/xa", root=str(proj), depth=0)
    assert g.entry == "sp:ota.sp::xa"
    for entry, msg in (("ota.sp:@cm", "defined in lib/devices.inc"), ("lib/devices.inc:xa", "holds nothing on the path"),
                       ("lib/devices.inc:.", "whole deck"), ("ota.sp:nope", "neither an instance path")):
        with pytest.raises(EntryNotFound) as ei:
            extract(entry, root=str(proj), deck="ota.sp")
        assert msg in str(ei.value), (entry, str(ei.value))
    both = tmp_path / "both"
    both.mkdir()
    (both / "d.sp").write_text("both\n.subckt x1 a b\nr1 a b 1k\n.ends\nx1 n1 0 x1\n.end\n")
    with pytest.raises(EntryNotFound) as ei:
        extract("d.sp:x1", root=str(both))
    assert "both an instance path and a subcircuit definition" in str(ei.value) and ei.value.suggestions == ["@x1", "/x1"]
    assert extract("d.sp:@x1", root=str(both)).entry == "sp:d.sp::@x1" and extract("d.sp:/x1", root=str(both)).entry == "sp:d.sp::x1"


def test_reformatted_deck_keeps_ids_and_hashes(tmp_path):
    proj = _proj(tmp_path, "ota")
    a = extract("ota.sp:.", root=str(proj), depth=None, dialect="ngspice")
    b = extract("ota_reformatted.sp:.", root=str(proj), depth=None, dialect="ngspice")
    strip = lambda g: {n.id.split("::", 1)[1]: n.body_hash for n in g.nodes.values() if n.kind != "module"}
    assert strip(a) == strip(b)                                                             # comments, case, layout, order: nothing moves
    norm = lambda i: "(deck)" if i.split("::", 1)[-1].startswith("(deck) ") else i.split("::", 1)[-1]
    assert {norm(e.src) + ">" + norm(e.dst or "") for e in a.edges} == {norm(e.src) + ">" + norm(e.dst or "") for e in b.edges}
    assert a.nodes[a.entry].body_hash != b.nodes[b.entry].body_hash                        # the deck's own scope was reordered


def test_two_decks_sharing_a_library_have_distinct_occurrence_ids(tmp_path):
    proj = _proj(tmp_path, "shared")
    a, b = extract("a.sp:.", root=str(proj), depth=None), extract("b.sp:.", root=str(proj), depth=None)
    assert "sp:a.sp::xdut.r1" in a.nodes and "sp:b.sp::xdut.r1" in b.nodes and not (_ids(a) & _ids(b))
    assert a.circuit["definitions"]["/dut"]["declarations"][0]["id"] == b.circuit["definitions"]["/dut"]["declarations"][0]["id"] == "sp:lib.inc::@dut"
    assert a.nodes["sp:a.sp::xdut.r1"].body_hash == b.nodes["sp:b.sp::xdut.r1"].body_hash


def test_unresolved_reasons_and_diagnostics(tmp_path):
    proj = _proj(tmp_path, "fail")
    g = extract("missing_include.sp:.", root=str(proj), depth=None)
    assert [u.reason.split(" (")[0] for u in g.unresolved] == ["no .subckt definition 'ghost' visible from scope ''"]
    assert [d["code"] for d in g.circuit["diagnostics"]] == ["missing-include", "missing-definition"] and "sp:missing_include.sp::r1" in g.nodes
    g = extract("duplicate_def.sp:.", root=str(proj), depth=None)
    assert g.unresolved[0].reason.startswith("ambiguous: 2 definitions of 'dup' in scope ''") and "duplicate_def.sp:2" in g.unresolved[0].reason
    g = extract("recursive.sp:.", root=str(proj), depth=None)
    reasons = sorted(u.reason for u in g.unresolved)
    assert reasons == ["recursive subcircuit instantiation (pa -> pb -> pa)", "recursive subcircuit instantiation (self -> self)"]
    assert "sp:recursive.sp::xs.r1" in g.nodes and "sp:recursive.sp::xm.x1" in g.nodes
    g = extract("wrong_terminals.sp:.", root=str(proj), depth=None)
    codes = sorted(d["code"] for d in g.circuit["diagnostics"])
    assert codes == ["terminal-count-mismatch"] * 3 and "sp:wrong_terminals.sp::x1.r1" in g.nodes
    g = extract("unsupported.sp:.", root=str(proj), depth=None)
    y1 = g.nodes["sp:unsupported.sp::y1"]
    assert y1.attrs["family"] == "?" and y1.params == [] and y1.attrs["tokens"].startswith("Y1 ")
    codes = sorted(d["code"] for d in g.circuit["diagnostics"])
    assert codes == ["encrypted-content", "unknown-device-family", "unknown-device-family", "unsupported-directive", "unsupported-directive"]
    assert [d["name"] for d in g.circuit["directives"] if d["role"] == "unknown"] == [".alter", ".bogus"]
    g = extract("missing_model.sp:.", root=str(proj), depth=None)
    assert g.circuit["models"]["/nosuchmodel"]["status"] == "missing" and sorted(d["code"] for d in g.circuit["diagnostics"]) == ["missing-model", "missing-model"]


def test_cache_hits_and_invalidation(tmp_path):
    proj = _proj(tmp_path, "ota")
    a = extract("ota.sp:.", root=str(proj), depth=None, dialect="ngspice")
    assert (a.meta["index"]["parsed"], a.meta["index"]["cached"]) == (4, 0)
    b = extract("ota.sp:.", root=str(proj), depth=None, dialect="ngspice")
    assert (b.meta["index"]["parsed"], b.meta["index"]["cached"]) == (0, 4) and {n.id: n.body_hash for n in a.nodes.values()} == {n.id: n.body_hash for n in b.nodes.values()}
    time.sleep(0.01)
    p = proj / "lib" / "tt_models.inc"
    p.write_text(p.read_text().replace("vto=0.4", "vto=0.41"))
    c = extract("ota.sp:.", root=str(proj), depth=None, dialect="ngspice")
    assert (c.meta["index"]["parsed"], c.meta["index"]["cached"]) == (1, 3)
    assert c.circuit["models"]["/nch"]["declarations"][0]["hash"] != a.circuit["models"]["/nch"]["declarations"][0]["hash"]
    time.sleep(0.01)
    (proj / "lib" / "ff_models.inc").write_text("* unselected section: never read\n")
    d = extract("ota.sp:.", root=str(proj), depth=None, dialect="ngspice")
    assert (d.meta["index"]["parsed"], d.meta["index"]["cached"]) == (0, 4)


def test_dependency_outside_root_is_recorded(tmp_path):
    proj = _proj(tmp_path, "ota")
    out = tmp_path / "libout"
    shutil.copytree(proj / "lib", out)
    deck = proj / "ota.sp"
    deck.write_text(deck.read_text().replace('.lib "lib/corners.lib" tt', f'.lib "{out}/corners.lib" tt'))
    g = extract("ota.sp:.", root=str(proj), depth=None, dialect="ngspice")
    lib = next(f for f in g.circuit["files"] if f["role"] == "lib")
    assert lib["outside_root"] and os.path.isabs(lib["path"]) and any(os.path.isabs(p) for p in g.meta["deps"])
    assert g.circuit["models"]["/pch"]["declarations"][0]["file"].startswith(str(out))


def test_frontend_finalize_is_reachable_without_api(tmp_path):
    from hx.traverse import TraverseOptions, extract_graph
    proj = _proj(tmp_path, "ota")
    fe = SpiceFrontend(str(proj), deck="ota.sp", dialect="ngspice")
    fe.build_index()
    g = extract_graph(fe, "ota.sp", ".", TraverseOptions(depth=1), str(proj))
    assert g.circuit is not None and set(g.circuit["terminals"]) <= set(g.nodes) and g.meta["deps"]
    d = json.loads(g.to_json())
    assert "circuit" in d and d["circuit"]["root"]["id"] == g.entry


# ---------------------------------------------------------------- PDK-style libraries and OSDI devices (coverage run, 2026-10-13)
_SPICE_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "spice")


def test_pdk_style_library_sections_continuations_and_ends_names(tmp_path):
    """GF180 `sm141064.ngspice` layout: a corner section pulls sibling sections of its own file (not a cycle); a
    `.param` continues across a blank line (ngspice joins `+` lines across blank and comment lines); `.ends othername`
    closes the subckt with a warning; diagnostics inside an unselected section (`ff` holds a stray `.ends`) are not
    reported because the simulator never reads them."""
    import collections
    root = tmp_path / "pdk"
    shutil.copytree(os.path.join(_SPICE_FIX, "pdk"), root)
    g = extract("pdk.sp:.", root=str(root), depth=None).to_dict()
    c = g["circuit"]
    codes = collections.Counter(d["code"] for d in c["diagnostics"])
    assert "include-cycle" not in codes and "unparsed-statement" not in codes and codes["ends-name-mismatch"] == 1, c["diagnostics"]
    assert sorted(s[1] for s in g["meta"]["index"]["sections"]) == ["common", "nfet_tt", "tt"]
    m0 = g["nodes"]["sp:pdk.sp::x1.m0"]
    assert m0["attrs"]["model"] == "nch" and m0["attrs"]["model_refs"][0]["key"] == "/nch" and "/nch" in c["models"]
    assert c["models"]["/nch"]["status"] == "found" and len(c["models"]["/nch"]["declarations"]) == 1      # ff's nch never read
    fe = SpiceFrontend(str(root), deck="pdk.sp")
    fe.build_index()
    rsh, dtemp = fe.index.decls[("param", (), "rsh")][0], fe.index.decls[("param", (), "dtemp")][0]
    assert rsh.line == dtemp.line == 12 and dtemp.end_line == 15 and rsh.file.endswith("models.lib")          # one statement across the blank line
    assert fe.index.decls[("param", (), "ldev")][0].line == 3 and fe.index.decls[("param", (), "ldev")][0].end_line == 6
    # the ff corner reads the other sibling and reports its stray .ends
    (root / "pdk.sp").write_text((root / "pdk.sp").read_text().replace('.lib "models.lib" tt', '.lib "models.lib" ff'))
    g2 = extract("pdk.sp:.", root=str(root), depth=None).to_dict()
    codes2 = collections.Counter(d["code"] for d in g2["circuit"]["diagnostics"])
    assert codes2["unparsed-statement"] == 1 and codes2["ends-name-mismatch"] == 1, g2["circuit"]["diagnostics"]
    assert sorted(s[1] for s in g2["meta"]["index"]["sections"]) == ["common", "ff", "nfet_ff"]


def test_osdi_devices_use_the_n_family(tmp_path):
    """ngspice's compiled Verilog-A (OSDI) devices start with `N`; their terminal layout is unknown, so terminals are
    named positionally and the model is the last positional token (IHP SG13G2 PSP models)."""
    root = tmp_path / "osdi"
    shutil.copytree(os.path.join(_SPICE_FIX, "osdi"), root)
    g = extract("osdi.sp:.", root=str(root), depth=None).to_dict()
    n1, n2 = g["nodes"]["sp:osdi.sp::n1"], g["nodes"]["sp:osdi.sp::n2"]
    assert n1["kind"] == "device" and n1["attrs"]["family"] == "N" and n1["attrs"]["element"] == "osdi" and n1["attrs"]["model"] == "osdi_nmos"
    assert [p["name"] for p in n1["params"]] == ["t1", "t2", "t3", "t4"] and [p["name"] for p in n2["params"]] == ["t1", "t2"]
    assert [t["as_written"] for t in g["circuit"]["terminals"]["sp:osdi.sp::n1"]] == ["d", "g", "0", "0"]
    assert n2["attrs"]["model"] == "osdi_res" and n1["attrs"]["parameters"] == {"w": "1u", "l": "0.13u"}
    assert not [d for d in g["circuit"]["diagnostics"] if d["code"] in ("unknown-device-family", "missing-model")], g["circuit"]["diagnostics"]


def test_nested_guard_ports_and_bindings_are_per_occurrence(tmp_path):
    """Four `xw.xl` variants: each instance's canonical port nets follow its own guarded ancestor (`xw#g0` binds
    n1/n2, `xw#g1` n2/n1), and the shared port net `xw.in` serialises one canonical net per binding."""
    g = extract("nested_guard.sp:.", root=str(_proj(tmp_path, "conditional")), depth=None, dialect="ngspice")
    c = g.circuit
    xl = [n.id for n in g.nodes.values() if n.qualname.startswith("xw.xl#")]
    assert len(xl) == 4
    pairs = sorted((c["ports"][i][0]["net"], c["ports"][i][1]["net"]) for i in xl)
    assert pairs == [("n1", "n2"), ("n1", "n2"), ("n2", "n1"), ("n2", "n1")]
    assert all(c["ports"][i][0]["outer"] in ("xw.in", "xw.out") for i in xl)                  # immediate bindings stay in xw's scope
    assert sorted(b["canonical"] for b in c["nets"]["xw.in"]["bindings"]) == ["n1", "n2"]
    r1 = [n.id for n in g.nodes.values() if n.qualname.startswith("xw.xl.r1#")]
    assert sorted(c["terminals"][i][0]["canonical"] for i in r1) == ["n1", "n1", "n2", "n2"] and all(c["terminals"][i][0]["net"] == "xw.xl.a" for i in r1)


def test_per_branch_declarations_are_all_serialized(tmp_path):
    """`leaf` and `dm` declared in both branches and used inside each: the records hold both alternatives even
    though every guarded device saw only its own branch's declaration (the first one used to win)."""
    g = extract("per_branch.sp:.", root=str(_proj(tmp_path, "conditional")), depth=None, dialect="ngspice")
    c = g.circuit
    leaf, dm = c["definitions"]["/leaf"], c["models"]["/dm"]
    assert leaf["status"] == "alternatives" and len({d["identity"] for d in leaf["declarations"]}) == 2 and len(leaf["declarations"]) == 2
    assert dm["status"] == "alternatives" and len({d["identity"] for d in dm["declarations"]}) == 2
    idents = {d["identity"] for d in leaf["declarations"]} | {d["identity"] for d in dm["declarations"]}
    for n in g.nodes.values():
        for ref in n.attrs.get("definition_refs", []) + n.attrs.get("model_refs", []):
            assert ref["key"] in idents, (n.id, ref)
    assert len(leaf["instances"]) == 4 and len(dm["used_by"]) == 2                               # x1 twice, x2 twice; d1 twice


def test_same_scope_duplicates_keep_both_cards(tmp_path):
    """Two unguarded cards of one name share an identity: both are kept (ambiguous), by source line. An ambiguous
    instance is a ghost, yet its candidates are listed with the ghost under `instances` and no body is expanded."""
    proj = _proj(tmp_path, "fail")
    g = extract("duplicate_model.sp:.", root=str(proj), depth=None)
    dm = g.circuit["models"]["/dm"]
    assert dm["status"] == "ambiguous" and [d["line"] for d in dm["declarations"]] == [2, 3] and {d["identity"] for d in dm["declarations"]} == {"/dm"}
    g = extract("duplicate_def.sp:.", root=str(proj), depth=None)
    dup = g.circuit["definitions"]["/dup"]
    ghost = next(u.id for u in g.unresolved if u.reason.startswith("ambiguous:"))
    assert dup["status"] == "ambiguous" and [d["line"] for d in dup["declarations"]] == [2, 5] and dup["instances"] == [ghost]
    assert ghost == "sp:duplicate_def.sp::x1" and not any(n.qualname.startswith("x1") for n in g.nodes.values())


def test_missing_definition_record_names_its_ghost(tmp_path):
    g = extract("missing_include.sp:.", root=str(_proj(tmp_path, "fail")), depth=None)
    ghost = next(u.id for u in g.unresolved if u.reason.startswith("no .subckt definition"))
    rec = g.circuit["definitions"]["/ghost"]
    assert rec["status"] == "missing" and rec["declarations"] == [] and rec["instances"] == [ghost] == ["sp:missing_include.sp::x1"]
    assert not any(n.qualname.startswith("x1") for n in g.nodes.values())


def test_shared_include_alternatives_both_survive(tmp_path):
    """One file included from `.if` and `.else`: same source line, two guarded declarations each — both survive."""
    g = extract("shared_include.sp:.", root=str(_proj(tmp_path, "conditional")), depth=None, dialect="ngspice")
    c = g.circuit
    for rec, line in ((c["definitions"]["/leaf"], 1), (c["models"]["/dm"], 4)):
        assert rec["status"] == "alternatives" and len(rec["declarations"]) == 2
        assert {(d["file"], d["line"]) for d in rec["declarations"]} == {("shared.inc", line)} and len({d["identity"] for d in rec["declarations"]}) == 2
    assert [f["path"] for f in c["files"]] == ["shared_include.sp", "shared.inc", "shared.inc"]


def test_standalone_library_entry_keeps_line_one(tmp_path):
    """`lib.inc:@leaf` without --deck reads the file as a library (line 1 kept) when line 1 is a dot-directive;
    the same file as a deck applies the title rule and names the pitfall; a deck's `@` entry stays a deck."""
    proj = _proj(tmp_path, "params")
    g = extract("inc_first_subckt.inc:@leaf", root=str(proj), depth=None)
    assert g.entry == "sp:inc_first_subckt.inc::@leaf" and "sp:inc_first_subckt.inc::@leaf.r1" in g.nodes
    assert g.meta["index"]["deck_role"] == "library" and g.circuit["root"]["deck_role"] == "library" and g.circuit["files"][0]["role"] == "library"
    assert g.meta["extract_args"]["deck"] is None and g.meta["index"]["deck"] == "inc_first_subckt.inc"
    assert not [d for d in g.circuit["diagnostics"] if d["code"] == "title-is-directive"]
    g2 = extract("inc_first_subckt.inc:.", root=str(proj), depth=None)
    assert g2.meta["index"]["deck_role"] == "deck" and [d["code"] for d in g2.circuit["diagnostics"]] == ["title-is-directive", "unparsed-statement"]
    with pytest.raises(EntryNotFound):
        extract("inc_first_subckt.inc:@leaf", root=str(proj), depth=None, deck="inc_first_subckt.inc")   # explicit --deck: the title rule wins
    ota = _proj(tmp_path, "ota")
    g3 = extract("ota.sp:@five_t_opamp", root=str(ota), depth=None)
    assert g3.meta["index"]["deck_role"] == "deck" and g3.circuit["root"] == {"kind": "definition", "id": g3.entry, "deck_role": "deck"}


def test_standalone_library_replays_from_stored_arguments(tmp_path):
    """The stored arguments keep `deck` omitted, so the viewer's re-extract and `hx watch` replay the library reading."""
    proj = _proj(tmp_path, "params")
    g = extract("inc_first_subckt.inc:@leaf", root=str(proj), depth=None)
    args = dict(g.meta["extract_args"])
    assert args["deck"] is None
    r = extract(args["entry"], **{k: v for k, v in args.items() if k != "entry"})     # what POST /api/extract does
    assert r.entry == g.entry and r.meta["index"]["deck_role"] == "library" and set(r.nodes) == set(g.nodes)
