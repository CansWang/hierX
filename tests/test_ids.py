from hx import ids


def H(text, lang="c"):
    return ids.body_hash(text, lang)


def test_body_hash_ignores_formatting_between_tokens():
    a = H(b"{ int x = 1;\n  return x; }")
    assert a == H(b"{int x=1; return x;}") == H(b"{ int x = 1 ; return x ; }") == H(b"{\n\tint x = 1;\n\treturn x;\n}")
    assert H("y = x+1;") == H("y = x + 1;") == H("y=x+1;")
    assert H("x = -1;") == H("x =-1;")            # maximal munch splits "=-" into "=" "-"
    assert a.startswith("sha1:")


def test_body_hash_sees_meaning():
    assert H(b"{ return 1; }") != H(b"{ return 2; }")
    assert H('f("a b");') != H('f("a  b");')       # whitespace inside a literal is significant
    assert H("c = 'x';") != H("c = ' ';")
    assert H("a--b;") != H("a - -b;")              # operator adjacency is significant
    assert H("a+++b;") != H("a + ++b;")
    assert H("int x;") != H("intx;")


def test_body_hash_ignores_comments():
    assert H("{ return 1; }") == H("{ return 1; /* why */ }") == H("{ // why\n return 1; }")
    assert H("{ return 1; }", "rs") == H("{ return 1; // note\n }", "rs")
    assert H("x = 1\n", "py") == H("x = 1  # note\n", "py") == H("# head\nx = 1\n", "py")
    assert H("y <= a + b;", "sv") == H("y <= a + b; // sum\n", "sv")
    assert H('s = "// not a comment";') != H('s = "";')


def test_python_indentation_is_significant_but_relative():
    conditional = "def f(c):\n    if c:\n        x = 1\n    return x\n"
    unconditional = "def f(c):\n    if c:\n    x = 1\n    return x\n"           # the reviewer's case
    assert H(conditional, "py") != H(unconditional, "py")
    nested = "    def f(c):\n        if c:\n            x = 1\n        return x\n"   # same body, moved into a class
    assert H(conditional, "py") == H(nested, "py")
    assert H(conditional, "py") == H("def f(c):\n\n    if c:\n        # c\n        x = 1\n\n    return x\n", "py")
    assert H("f(a,\n  b)\n", "py") == H("f(a, b)\n", "py")                       # implicit line joining inside brackets
    assert H("s = f'{x}  y'\n", "py") != H("s = f'{x} y'\n", "py")


def test_language_literals():
    assert H("let s = r#\"a \" b\"#;", "rs") != H("let s = r#\"a  \" b\"#;", "rs")
    assert H("fn f<'a>(x: &'a str) {}", "rs") == H("fn f<'a>(x: &'a  str) {}", "rs")  # lifetimes are not char literals
    assert ids.tokenize("assign z = 8'hFF + 'h1 + 4'b1010;", "sv")[3:4] == ["8'hFF"]
    assert H("y <= a - b;", "sv") != H("y <= a + b;", "sv")
    assert H('R"x(a  b)x"') != H('R"x(a b)x"')


def test_type_id_forms():
    assert ids.type_id("c", "include/dma.h", "struct", "dma_chan") == "c:include/dma.h::struct dma_chan"
    assert ids.type_id("c", "include/dma.h", "typedef", "dma_chan_t") == "c:include/dma.h::dma_chan_t"
    assert ids.type_id("c", "include/dma.h", "union", "", anonymous=True, line=20) == "c:include/dma.h::anon@L20"


def test_disambiguate_only_touches_collisions():
    out = ids.disambiguate({"u1": "cpp:a.cpp::f", "u2": "cpp:a.cpp::f", "u3": "cpp:a.cpp::g"})
    assert out["u3"] == "cpp:a.cpp::g"
    assert out["u1"] != out["u2"]
    assert out["u1"].startswith("cpp:a.cpp::f#") and out["u2"].startswith("cpp:a.cpp::f#")


def test_rel_outside_root_is_absolute(tmp_path):
    inside = tmp_path / "src" / "a.c"
    assert ids.rel(str(inside), str(tmp_path)) == "src/a.c"
    assert ids.rel("/usr/include/stdio.h", str(tmp_path)) == "/usr/include/stdio.h"
