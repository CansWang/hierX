"""Typed statements: the title rule precedes grouping, includes keep line 1, PARAMS: and // comments, grammar splits."""
import dataclasses
import os

from hx.netlist import parser
from hx.netlist.grammar import SpiceGrammar
from hx.netlist.lexer import tokenize
from hx.netlist.profiles import NGSPICE, SPICE, SPICE_FAMILIES, sniff_dialect

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "spice")


def _structure(path, role, profile=NGSPICE):
    return parser.structure(parser.lex_file(path, profile), role, profile)


def test_title_rule_precedes_structure():
    """A deck whose first line reads `.subckt fake a b` keeps that line as the title (ngspice does), so no false
    subcircuit swallows the rest; the same file read as an include keeps the declaration."""
    fs = _structure(os.path.join(FIX, "title", "dot_title.sp"), "deck")
    kinds = [type(s).__name__ for s in fs.statements]
    assert kinds == ["Title", "Element", "SubcktDef", "Element", "EndStmt"] and fs.title == ".subckt fake a b"
    assert fs.statements[2].name == "real" and [d["code"] for d in fs.diagnostics] == ["title-is-directive"]   # the pitfall is named
    inc = _structure(os.path.join(FIX, "title", "dot_title.sp"), "include")
    assert type(inc.statements[0]).__name__ == "SubcktDef" and inc.statements[0].name == "fake"


def test_include_keeps_a_subckt_on_line_one():
    fs = _structure(os.path.join(FIX, "params", "inc_first_subckt.inc"), "include")
    assert [type(s).__name__ for s in fs.statements] == ["SubcktDef"] and fs.statements[0].ports == ["a", "b"]


def test_params_keyword_and_double_slash_comment():
    fs = _structure(os.path.join(FIX, "params", "params.sp"), "deck")
    sd = next(s for s in fs.statements if isinstance(s, parser.SubcktDef))
    assert sd.name == "outer_b" and sd.ports == ["in", "out"] and sd.params == [("rv", "3k")] and "//" not in sd.text
    xb = next(s for s in fs.statements if isinstance(s, parser.Element) and s.name == "xb")
    parts = SpiceGrammar().split_element(xb.tokens(NGSPICE), SPICE_FAMILIES["X"], lambda n: False)
    assert parts.positional == ["n2", "n3"] and parts.master == "outer_b" and parts.params == [("rv", "5k")]


def test_grouping_of_conditionals_libs_models_and_errors(tmp_path):
    text = ("t\n.if (a > 0)\nr1 x 0 1k\n.elseif (a < 0)\nr1 x 0 2k\n.else\nr1 x 0 3k\n.endif\n.lib \"f.lib\" tt\n.lib mysect\nr2 x 0 1k\n.endl\n"
            ".model nch nmos level=1 vto=0.4\n.param a=1 b={a*2}\n.global vdd vss\n.bogus 1 2\n.subckt open a b\nr3 a b 1k\n")
    p = tmp_path / "d.sp"
    p.write_text(text)
    fs = _structure(str(p), "deck")
    names = [type(s).__name__ for s in fs.statements]
    assert names == ["Title", "Conditional", "LibRef", "LibSection", "ModelStmt", "ParamStmt", "GlobalStmt", "Directive", "SubcktDef"]
    c = fs.statements[1]
    assert [b[0] for b in c.branches] == ["(a > 0)", "(a < 0)", ""] and c.has_else and all(len(b[1]) == 1 for b in c.branches)
    assert fs.statements[2].section == "tt" and fs.statements[3].name == "mysect" and len(fs.statements[3].body) == 1
    assert (fs.statements[4].name, fs.statements[4].type, fs.statements[4].params_text) == ("nch", "nmos", "level=1 vto=0.4")
    assert fs.statements[5].assignments == [("a", "1"), ("b", "{a*2}")] and fs.statements[6].names == ["vdd", "vss"]
    assert fs.statements[7].role == "unknown"
    codes = sorted(d["code"] for d in fs.diagnostics)
    assert codes == ["unparsed-statement", "unsupported-directive"]                      # the unclosed .subckt and .bogus


def test_element_grammar_resolves_optional_model_by_scope():
    g = SpiceGrammar()
    models = {"npnmod", "rmod", "nch"}
    is_model = lambda n: n in models
    split = lambda line, letter: g.split_element(tokenize(line, NGSPICE), SPICE_FAMILIES[letter], is_model)
    q1, q2 = split("q1 c b e 0 npnmod", "Q"), split("q2 c b e npnmod", "Q")
    assert (q1.positional, q1.master) == (["c", "b", "e", "0"], "npnmod") and (q2.positional, q2.master) == (["c", "b", "e"], "npnmod")
    r1, r2 = split("r1 a b 1k", "R"), split("r2 a b rmod 1k", "R")
    assert (r1.positional, r1.master, r1.value) == (["a", "b"], None, "1k") and (r2.master, r2.value) == ("rmod", "1k")
    m = split("m1 d g s b nch w=1u l=2u", "M")
    assert m.positional == ["d", "g", "s", "b"] and m.master == "nch" and m.params == [("w", "1u"), ("l", "2u")]
    e4, e2 = split("e1 a b c d 2", "E"), split("e1 a b value={v(c)}", "E")
    assert (e4.positional, e4.value) == (["a", "b", "c", "d"], "2") and e2.positional == ["a", "b"] and e2.params == [("value", "{v(c)}")]
    f, k = split("f1 a b vs 2", "F"), split("k1 l1 l2 0.5", "K")
    assert (f.positional, f.refs, f.value) == (["a", "b"], ["vs"], "2") and (k.positional, k.refs, k.value) == ([], ["l1", "l2"], "0.5")
    x = g.split_element(tokenize("x1 a b c sub w=1", NGSPICE), SPICE_FAMILIES["X"], is_model)
    assert (x.positional, x.master, x.params) == (["a", "b", "c"], "sub", [("w", "1")])
    bad = split("m1 d g nch", "M")
    assert "model-not-visible" in bad.diagnostics or any(d.startswith("only") for d in bad.diagnostics)


def test_profiles_differ_only_in_data_and_sniffing():
    diff = {f.name for f in dataclasses.fields(SPICE) if getattr(SPICE, f.name) != getattr(NGSPICE, f.name)}
    assert diff == {"name", "inline_comment", "directives"}
    assert sniff_dialect("t\n.control\n.endc\n") == "ngspice" and sniff_dialect("t\n.if (a)\n.endif\n") == "ngspice"
    assert sniff_dialect("t\nr1 a b 1k\n") == "spice" and sniff_dialect("simulator lang=spectre\n") == "spectre"


def test_switch_grammar_orders_refs_before_models():
    """Terminals, then controlling references, then the model, then the value: `W1 out 0 VSENSE sm` keeps its model
    (it used to become the value, leaving `missing-model` and an oracle that skipped the comparison)."""
    g = SpiceGrammar()
    is_model = lambda n: n.lower() in {"sm", "sw"}
    split = lambda line, letter: g.split_element(tokenize(line, NGSPICE), SPICE_FAMILIES[letter], is_model)
    w = split("W1 out 0 VSENSE sm", "W")
    assert (w.positional, w.refs, w.master, w.value, w.diagnostics) == (["out", "0"], ["VSENSE"], "sm", None, [])
    w2 = split("w2 out 0 vsense sm on", "W")
    assert (w2.master, w2.value) == ("sm", "on")
    s = split("s1 a b c d sw", "S")
    assert (s.positional, s.master, s.refs) == (["a", "b", "c", "d"], "sw", [])
    f, h, k = split("f1 a b vs 2", "F"), split("h1 a b vs 1k", "H"), split("k1 l1 l2 0.5", "K")
    assert (f.refs, f.master, f.value) == (["vs"], None, "2") and (h.refs, h.value) == (["vs"], "1k") and (k.refs, k.value) == (["l1", "l2"], "0.5")
    assert "missing model" in split("w3 out 0 vsense", "W").diagnostics


def test_every_structural_error_is_a_diagnostic_and_the_text_is_kept():
    """Misplaced or operand-less directives never abort: each one is an `unparsed-statement` naming the problem."""
    fs = _structure(os.path.join(FIX, "fail", "malformed.sp"), "deck")
    messages = sorted(d["message"] for d in fs.diagnostics if d["code"] == "unparsed-statement")
    assert messages == sorted([".elseif without .if", ".else without .if", ".endif without .if", ".ends without an open .subckt",
                               ".endl without .lib section", ".lib without arguments", ".include without a path",
                               ".model needs a name and a type", ".subckt without a name", "continuation line without a statement",
                               ".if never closed"])
    assert {d["code"] for d in fs.diagnostics} == {"unparsed-statement"}
    kept = [s.raw.text for s in fs.statements if type(s).__name__ == "Unparsed"]
    assert ".model onlyname" in kept and ".subckt" in kept and "orphan continuation" in kept
    assert [type(s).__name__ for s in fs.statements if type(s).__name__ in ("Element", "Conditional", "ControlBlock")] == ["Element", "ControlBlock", "Conditional"]
