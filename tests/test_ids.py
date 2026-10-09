from hx import ids


def test_body_hash_ignores_whitespace():
    a = ids.body_hash(b"{ int x = 1;\n  return x; }")
    b = ids.body_hash(b"{int x=1; return x;}".replace(b"=1", b" = 1").replace(b"x;", b"x ;"))
    c = ids.body_hash(b"{   int x = 1;   return x;   }")
    assert a == c
    assert a != b  # token boundary moved ("x ;" vs "x;") is a real change
    assert ids.body_hash(b"{ return 1; }") != ids.body_hash(b"{ return 2; }")
    assert a.startswith("sha1:")


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
