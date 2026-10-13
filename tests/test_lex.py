"""The span-keeping lexer and the expression helpers built on it (review findings H1, H3, C2, C3)."""
from hx import ids

SAMPLES = {
    "c": 'int f(int a){ /* c */ return a + "x  y"[0]; } // t\n',
    "py": 'def f(a):\n    s = """x,\n  y"""  # c\n    return a < b\n',
    "rs": "fn f<'a>(x: &'a str) -> &'a str { let c = 'q'; r#\"raw \"\"# ; x }\n",
    "sv": "module m; logic [7:0] v = 8'hFF; // c\nendmodule\n",
}

# Computed on the tree before `lex` existed: the hash of a body must not move when the lexer is refactored.
GOLDEN = {
    "c": "sha1:f63079e1ffdd746ec9199ec760c3fb147e60032c",
    "py": "sha1:5bd3bbb8547dd87a03143b00f28bde5955524b63",
    "rs": "sha1:ed5791333725b9330db0bd3719138c716c395aa3",
    "sv": "sha1:5814155a41f240712b534968eba8f8e65e1b70db",
}


def test_lex_spans_roundtrip():
    for lang, text in SAMPLES.items():
        toks = ids.lex(text, lang)
        assert [t.text for t in toks] == ids.tokenize(text, lang)
        for t in toks:
            if t.kind == "indent":
                assert t.start == t.end                      # synthetic: no source span
            else:
                assert text[t.start:t.end] == t.text, (lang, t)
        assert {t.kind for t in toks} <= {"ident", "number", "string", "char", "op", "indent"}


def test_body_hash_golden():
    for lang, text in SAMPLES.items():
        assert ids.body_hash(text, lang) == GOLDEN[lang], lang


def test_split_top_respects_strings():
    assert ids.split_top('a, "x, y", f(b, c)', "py") == ["a", '"x, y"', "f(b, c)"]
    assert ids.split_top('NULL, "o %d, s", p->x', "c") == ["NULL", '"o %d, s"', "p->x"]
    assert ids.split_top("a, Vec<(i32, u8)>, d<x, y>", "rs", angle=True) == ["a", "Vec<(i32, u8)>", "d<x, y>"]
    assert ids.split_top("a < b, c", "py") == ["a < b", "c"]                    # `<` is not a bracket in Python
    assert ids.split_top("' 2>&1 ', [a, b]", "py") == ["' 2>&1 '", "[a, b]"]    # `>` inside a string never closes
    assert ids.split_top("a /* , */ b, c", "c") == ["a b", "c"]                  # a comma in a comment is not a separator
    assert ids.split_top("", "c") == [] and ids.split_top(" , ", "c") == []


def test_squash_ws_keeps_literals():
    assert ids.squash_ws('"   "') == '"   "'
    assert ids.squash_ws("a   +\n  b") == "a + b"
    assert ids.squash_ws("a/*c*/b") == "a b"                                    # a removed comment separates
    assert ids.squash_ws("pc->x") == "pc->x" and ids.squash_ws("pc -> x") == "pc -> x"
    assert ids.squash_ws('f(\n    """x,\n  y""",   # c\n    b)\n', "py") == 'f("""x,\n  y""", b)'
    assert ids.squash_ws('f(a,   # c\n    b)\n', "py") == "f(a, b)"
    assert ids.squash_ws("", "c") == ""


def test_paren_args_and_partition():
    assert ids.paren_args('MAC(a, f(b, c), "x, y")') == ["a", "f(b, c)", '"x, y"']
    assert ids.paren_args("FUNCC(x)(pix, s)") == ["x"]                             # the first list only
    assert ids.paren_args("(pix, sizeof(pixel), 4)") == ["pix", "sizeof(pixel)", "4"]
    assert ids.paren_args("av_clip") == [] and ids.paren_args("f(a, b") == []
    assert ids.paren_args("MAC(a, , b,)", keep_empty=True) == ["a", "", "b", ""]    # C macro: empty arguments are positional
    assert ids.paren_args("MAC(a, , b)") == ["a", "b"] and ids.paren_args("MAC()", keep_empty=True) == []
    assert ids.paren_span("x = f(a) + g(b)") == (5, 7)
    assert ids.partition_top('sep: str = ","', "py", "=") == ("sep: str", '","')
    assert ids.partition_top('s: str = "a=b"', "py", "=") == ("s: str", '"a=b"')
    assert ids.partition_top("x: Callable[[int, str], None]", "py", ":") == ("x", "Callable[[int, str], None]")
    assert ids.partition_top("plain", "py", "=") == ("plain", None)
