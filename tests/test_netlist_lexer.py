"""Netlist lexer: statements with spans, continuation, comment markers per profile, verbatim regions, tokens."""
from hx.netlist import lexer
from hx.netlist.profiles import NGSPICE, SPICE


def test_continuation_joins_with_piece_spans():
    st = lexer.read_statements("title\nr1 a b 1k\n* a comment between\n+ tc=1\n+   tc2=2\n\n+ tc3=3\nc1 a b 1p\n", NGSPICE, "d.sp")
    assert [(s.line, s.end_line, s.text) for s in st] == [(1, 1, "title"), (2, 7, "r1 a b 1k tc=1 tc2=2 tc3=3"), (8, 8, "c1 a b 1p")]
    assert st[1].pieces == [(2, 0, "r1 a b 1k"), (4, 1, "tc=1"), (5, 1, "tc2=2"), (7, 1, "tc3=3")]   # (line, col, fragment) as written
    orphan = lexer.read_statements("+ orphan\nr1 a b 1k\n", NGSPICE, "d.sp")                    # neither a comment nor a blank line ends a
    assert orphan[0].kind_hint == "unparsed" and orphan[0].text == "orphan"                   # continuation (ngspice 45.2); a leading `+` is


def test_inline_comment_markers_follow_the_profile():
    ng = lexer.read_statements("t\nr1 a b 1k $ note\nr2 a b 2k ; note\nr3 a b 3k // note\nr4 a $G_1 1k\nr5 a b {1k $ x}\n", NGSPICE, "d.sp")
    assert [s.text for s in ng[1:]] == ["r1 a b 1k", "r2 a b 2k", "r3 a b 3k", "r4 a $G_1 1k", "r5 a b {1k $ x}"]
    sp = lexer.read_statements("t\nr1 a b 1k $ note\n", SPICE, "d.sp")
    assert sp[1].text == "r1 a b 1k $ note"                                                 # plain SPICE has no inline comments


def test_verbatim_regions_and_end():
    st = lexer.read_statements("t\n.control\nrun\n* not a comment here\n.endc\n.prot\nr_secret a b 1k\n.unprot\nr1 a b 1k\n.end\nr_after a b 1k\n", NGSPICE, "d.sp")
    kinds = [(s.kind_hint, s.line, s.end_line) for s in st]
    assert kinds == [("element", 1, 1), ("control", 2, 5), ("encrypted", 6, 8), ("element", 9, 9), ("dot", 10, 10)]
    assert st[1].text == ".control\nrun\n* not a comment here\n.endc" and st[2].text.endswith(".unprot")
    assert not any("r_after" in s.text for s in st)                                         # nothing after .end


def test_tokens():
    toks = lexer.tokenize("m1 a b 0 0 nch w={w*2} l='0.1u' PARAMS: x=1 s=\"a b\" (p, q)", NGSPICE)
    assert [(t.kind, t.text) for t in toks] == [("name", "m1"), ("name", "a"), ("name", "b"), ("number", "0"), ("number", "0"), ("name", "nch"),
                                               ("name", "w"), ("assign", "="), ("expr", "{w*2}"), ("name", "l"), ("assign", "="), ("expr", "'0.1u'"),
                                               ("keyword", "PARAMS:"), ("name", "x"), ("assign", "="), ("number", "1"), ("name", "s"), ("assign", "="),
                                               ("string", '"a b"'), ("punct", "("), ("name", "p"), ("punct", ","), ("name", "q"), ("punct", ")")]
    positional, pairs = lexer.assignments(lexer.tokenize("x1 a b 1 sub params: w=1 l={2*x}", NGSPICE))
    assert [t.text for t in positional] == ["x1", "a", "b", "1", "sub"] and pairs == [("w", "1"), ("l", "{2*x}")]
    assert [t.kind for t in lexer.tokenize("1 2.5 1e-3 -4 4.7k", NGSPICE)] == ["number"] * 5
