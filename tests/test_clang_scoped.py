"""Symbol identity across translation units (review finding C1 and the BufferSinkContext collision; review rounds
3-8): file-scoped keys for non-external symbols, declaration/definition reconciliation of types, variants by SCC
fingerprint, symlink-independent ids (C4) and cache invalidation."""
import json
import os
import shutil
import subprocess
import time

import pytest

from hx import ids
from hx.api import extract as _extract

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "c_scoped")
ALL = ["a/options.c", "b/options.c", "t1.c", "t2.c", "t3.c", "impl.c", "main.c", "d1.c", "d2.c", "d3.c",
       "w1.c", "w2.c", "r1.c", "r2.c", "s1.c", "s2.c", "t4.c", "t5.c", "l.c", "oa.c", "ob.c", "oc.c", "od.c", "lf1.c", "lf2.c", "ra1.c", "ra2.c"]
FLAGS = {"w1.c": "-DWIDE", "r3.c": "-DGROW", "lf1.c": "-DWIDE"}
CPP = os.path.join(os.path.dirname(__file__), "fixtures", "cpp_rec")


def _project(tmp_path, files=ALL, name="scoped", src=FIX):
    proj = tmp_path / name
    shutil.copytree(src, proj, ignore=shutil.ignore_patterns(".hx", "__pycache__"))
    _write_cc(proj, files)
    return proj


def _write_cc(proj, files, compiler="gcc"):
    (proj / "build").mkdir(exist_ok=True)
    cc = [{"directory": str(proj), "file": f"src/{f}",
           "command": f"{compiler} -Iinclude {FLAGS.get(f, '')} -c src/{f} -o build/{f.replace('/', '_')}.o"} for f in files]
    (proj / "build" / "compile_commands.json").write_text(json.dumps(cc))


def _run(proj, entry, **kw):
    kw.setdefault("jobs", 1)
    kw.setdefault("depth", 3)
    return _extract(entry, root=str(proj), **kw)


def _shape(g):
    d = g.to_dict()
    return {"nodes": d["nodes"], "types": d["types"], "globals": d["globals"],
            "edges": sorted((e["from"], e.get("to") or "", e["kind"], tuple(e.get("args") or [])) for e in d["edges"]),
            "unresolved": sorted((u["name"], u["from"], u["reason"]) for u in d["unresolved"])}


def _gcc_sizeof(proj, includes, exprs, flags=""):
    """Ground truth from the compiler: sizeof(expr) for each expr, with the given includes (headers or .c files)."""
    d = proj / "probe"
    d.mkdir(exist_ok=True)
    src = "#include <stdio.h>\n" + "".join(f'#include "{i}"\n' for i in includes) + "int main(void){" + \
          "".join(f'printf("%zu\\n", sizeof({e}));' for e in exprs) + "return 0;}\n"
    (d / "p.c").write_text(src)
    subprocess.run(["gcc", "-I", str(proj / "include"), "-I", str(proj), *flags.split(), str(d / "p.c"), "-o", str(d / "p")], check=True)
    out = subprocess.run([str(d / "p")], capture_output=True, text=True, check=True).stdout.split()
    return [int(x) for x in out]


def _gcc_run(proj, sources, calls, flags="", compiler="gcc"):
    """Ground truth for what `sizeof` in a generated `main` cannot see (function-local types): the generated `main`
    CALLS the fixture functions, which return the size of their own local type, and prints the values."""
    d = proj / "probe"
    d.mkdir(exist_ok=True)
    ext, proto = ("cpp", "int {n}();") if compiler == "g++" else ("c", "int {n}(void);")
    src = "#include <stdio.h>\n" + "".join(proto.format(n=n) + "\n" for n in calls) + "int main(void){" + \
          "".join(f'printf("%d\\n", {n}());' for n in calls) + "return 0;}\n"
    (d / f"p.{ext}").write_text(src)
    subprocess.run([compiler, "-I", str(proj / "include"), "-I", str(proj), *flags.split(), str(d / f"p.{ext}"),
                    *[str(proj / x) for x in sources], "-o", str(d / "p")], check=True)
    return [int(x) for x in subprocess.run([str(d / "p")], capture_output=True, text=True, check=True).stdout.split()]


def _variants(g, prefix):
    return sorted(t for t in g.types if t.startswith(prefix))


def _shape_sans_loc(g):
    """`_shape` with every `loc` removed: what a comment-only edit above the code is allowed to change."""
    d = _shape(g)
    for sec in ("nodes", "types", "globals"):
        d[sec] = {k: {f: v for f, v in rec.items() if f != "loc"} for k, rec in d[sec].items()}
    return d


def test_scoped_identity(tmp_path):
    proj = _project(tmp_path)
    ga, gb = _run(proj, "src/a/options.c:run_a"), _run(proj, "src/b/options.c:run_b")
    assert set(ga.nodes) == {"c:src/a/options.c::run_a", "c:src/a/options.c::get_category", "c:src/a/options.c::cb",
                             "c:include/shared.h::twice"}
    assert set(gb.nodes) == {"c:src/b/options.c::run_b", "c:src/b/options.c::get_category", "c:src/b/options.c::cb",
                             "c:include/shared.h::twice"}
    assert not any("#" in i for i in list(ga.nodes) + list(gb.nodes))          # no residual collision hashes
    assert ("c:src/a/options.c::run_a", "c:src/a/options.c::cb", "ref") in {(e.src, e.dst, e.kind) for e in ga.edges}
    assert ("c:src/b/options.c::run_b", "c:src/b/options.c::cb", "ref") in {(e.src, e.dst, e.kind) for e in gb.edges}
    assert ga.nodes["c:src/a/options.c::cb"].globals.writes == ["c:src/a/options.c::counter"]
    assert gb.nodes["c:src/b/options.c::cb"].globals.writes == ["c:src/b/options.c::counter"]
    # struct ctx: one layout per directory, both matching the compiler
    sa, sb = _gcc_sizeof(proj, ["src/a/options.c"], ["struct ctx"]), _gcc_sizeof(proj, ["src/b/options.c"], ["struct ctx"])
    assert ga.types["c:src/a/options.c::struct ctx"].size == sa[0] and gb.types["c:src/b/options.c::struct ctx"].size == sb[0]
    assert sa != sb
    assert ga.types["c:src/a/options.c::ctx_t"].underlying_ref == "c:src/a/options.c::struct ctx"
    assert gb.types["c:src/b/options.c::ctx_t"].underlying_ref == "c:src/b/options.c::struct ctx"
    assert ga.nodes["c:src/a/options.c::get_category"].params[0].type_ref == "c:src/a/options.c::ctx_t"
    # the header-defined static inline is ONE function with three callers, not a build variant
    gt = _run(proj, "include/shared.h:twice", include_callers=True, depth=1)
    assert gt.entry == "c:include/shared.h::twice" and gt.meta["index"]["variants"] == 0
    assert {n.id for n in gt.nodes.values() if n.depth < 0} == {"c:src/a/options.c::get_category", "c:src/b/options.c::get_category",
                                                                "c:src/main.c::app"}
    # callers of the b helper come from b only, and the entry resolves to the b definition
    gc = _run(proj, "src/b/options.c:get_category", include_callers=True, depth=1)
    assert gc.entry == "c:src/b/options.c::get_category"
    assert {n.id for n in gc.nodes.values() if n.depth < 0} == {"c:src/b/options.c::run_b"}
    # cache states cannot change the index
    cold = _shape(ga)
    assert _shape(_run(proj, "src/a/options.c:run_a")) == cold
    time.sleep(0.01)
    p = proj / "src" / "b" / "options.c"
    p.write_text(p.read_text())
    os.utime(p, None)
    partial = _run(proj, "src/a/options.c:run_a")
    assert partial.meta["index"]["parsed"] == 1 and _shape(partial) == cold
    assert _shape(_run(proj, "src/a/options.c:run_a", use_cache=False)) == cold


def test_forward_declared_type_is_one_type_regardless_of_include_order(tmp_path):
    proj = _project(tmp_path)
    graphs = {i: _run(proj, f"src/t{i}.c:f{i}") for i in (1, 2, 3)}
    for i, g in graphs.items():
        n = g.nodes[f"c:src/t{i}.c::f{i}"]
        assert n.params[0].type_ref == "c:include/shared.h::fwd_t"
        assert g.types["c:include/shared.h::fwd_t"].underlying_ref == "c:include/complete.h::struct fwd"
        assert g.types["c:include/complete.h::struct fwd"].size == 8 and [x.name for x in g.types["c:include/complete.h::struct fwd"].fields] == ["x", "y"]
        assert not [t for t in g.types if "fwd" in t and "@" in t]                       # no variants, no stub id
    shapes = [_shape(g) for g in graphs.values()]
    reversed_proj = _project(tmp_path, list(reversed(ALL)), name="reversed")           # TU order must not matter
    assert [_shape(_run(reversed_proj, f"src/t{i}.c:f{i}")) for i in (1, 2, 3)] == shapes


def test_shared_forward_declaration_with_two_definitions_is_not_merged(tmp_path):
    proj = _project(tmp_path)
    g1, g2, g3 = (_run(proj, f"src/d{i}.c:d{i}") for i in (1, 2, 3))
    assert g1.types["c:src/d1.c::struct dup"].size == 4 and g2.types["c:src/d2.c::struct dup"].size == 16
    stub = g3.types["c:include/common.h::struct dup"]
    assert stub.size is None and stub.fields == []
    assert any("struct dup: declared in include/common.h but defined differently in src/d1.c, src/d2.c" in n for n in g3.meta["notes"])


def test_shared_typedef_over_conflicting_definitions_is_split(tmp_path):
    proj = _project(tmp_path)
    g1, g2, g3 = (_run(proj, f"src/d{i}.c:d{i}") for i in (1, 2, 3))
    v1, v2, v3 = (_variants(g, "c:include/common.h::dup_t@") for g in (g1, g2, g3))
    assert len(v1) == len(v2) == len(v3) == 1 and len({v1[0], v2[0], v3[0]}) == 3
    assert g1.types[v1[0]].underlying_ref == "c:src/d1.c::struct dup" and g1.types[v1[0]].size == 4
    assert g2.types[v2[0]].underlying_ref == "c:src/d2.c::struct dup" and g2.types[v2[0]].size == 16
    assert g3.types[v3[0]].underlying_ref == "c:include/common.h::struct dup" and g3.types[v3[0]].size is None
    assert g1.nodes["c:src/d1.c::d1"].params[0].type_ref == v1[0] and g3.nodes["c:src/d3.c::d3"].params[0].type_ref == v3[0]
    assert any("typedef dup_t: 3 different layouts/targets" in n for n in g1.meta["notes"])
    assert _shape(_run(proj, "src/d1.c:d1")) == _shape(g1)                              # warm == cold


def test_wrapper_over_variant_targets_is_split(tmp_path):
    proj = _project(tmp_path)
    g1, g2 = _run(proj, "src/d1.c:d1"), _run(proj, "src/d2.c:d2")
    b1, b2 = _variants(g1, "c:include/common.h::struct box@"), _variants(g2, "c:include/common.h::struct box@")
    assert len(b1) == len(b2) == 1 and b1 != b2
    assert [(f.name, f.offset, f.size) for f in g1.types[b1[0]].fields] == [(f.name, f.offset, f.size) for f in g2.types[b2[0]].fields]
    assert g1.types[b1[0]].fields[0].type_ref == _variants(g1, "c:include/common.h::dup_t@")[0]
    assert g2.types[b2[0]].fields[0].type_ref == _variants(g2, "c:include/common.h::dup_t@")[0]
    assert g1.types[b1[0]].fields[0].type_ref != g2.types[b2[0]].fields[0].type_ref
    gm = _run(proj, "src/main.c:walk", type_depth=3)
    assert "c:include/shared.h::struct node" in gm.types                                   # self-reference: one plain id
    assert gm.types["c:include/shared.h::struct node"].fields[0].type_ref == "c:include/shared.h::struct node"


def test_opaque_tag_is_not_attached_to_an_unrelated_definition(tmp_path):
    proj = _project(tmp_path)
    g = _run(proj, "src/main.c:use_handle")
    stub = g.types["c:include/handle.h::struct handle"]
    assert stub.size is None and stub.fields == [] and "c:src/impl.c::struct handle" not in g.types
    assert g.nodes["c:src/main.c::use_handle"].params[0].type_ref == "c:include/handle.h::struct handle"
    gi = _run(proj, "src/impl.c:use_impl_handle")
    assert gi.types["c:src/impl.c::struct handle"].size == 12
    assert not any("handle" in n for n in g.meta["notes"] + gi.meta["notes"])


def test_unrelated_definition_leaves_variant_ids_unchanged(tmp_path):
    """Review round 9: `struct hbox` points at the opaque `struct handle` of handle.h; src/impl.c defines an UNRELATED
    complete `struct handle` that never meets that declaration. Its presence in the build must not change a single
    id, including the `@<8hex>` of the hbox variants (one per dup_t target)."""
    with_impl = _project(tmp_path, name="with")
    without = _project(tmp_path, [f for f in ALL if f != "impl.c"], name="without")
    seen = []
    for entry in ("src/d1.c:d1_hbox", "src/d2.c:d2_hbox"):
        a, b = _run(with_impl, entry), _run(without, entry)
        assert set(a.types) == set(b.types) and set(a.nodes) == set(b.nodes) and _shape(a) == _shape(b), entry
        hb = _variants(a, "c:include/hbox.h::struct hbox@")
        assert len(hb) == 1 and a.types[hb[0]].fields[1].type_ref == "c:include/handle.h::struct handle"
        assert a.types["c:include/handle.h::struct handle"].size is None and "c:src/impl.c::struct handle" not in a.types
        seen.append(hb[0])
    assert seen[0] != seen[1]                                                              # still split by dup_t


def test_declaration_chain_links_every_declaration(tmp_path):
    """Review round 9: fwd2.h forward-declares `struct fwd` and is never a TU's FIRST declaration of it (t4.c includes
    complete.h first); t5.c sees only fwd2.h. A chain of every declaration file links fwd2.h to the definition."""
    proj = _project(tmp_path)
    g4, g5 = _run(proj, "src/t4.c:f4"), _run(proj, "src/t5.c:t5")
    for g, fn in ((g4, "c:src/t4.c::f4"), (g5, "c:src/t5.c::t5")):
        assert g.nodes[fn].params[0].type_ref == "c:include/complete.h::struct fwd"
        assert g.types["c:include/complete.h::struct fwd"].size == 8 and [x.name for x in g.types["c:include/complete.h::struct fwd"].fields] == ["x", "y"]
        assert not [t for t in g.types if "fwd2" in t or ("fwd" in t and "@" in t)]


def test_shared_typedef_links_two_opaque_declarations(tmp_path):
    """Review round 10, refined on FFmpeg: a_opaque.h and b_opaque.h each declare `struct opq` and no TU sees both, but
    both TUs see opq.h's `typedef struct opq opq_t;`, which in each TU names that TU's `struct opq`. That shared
    declaration is evidence (nothing about layouts): one declaration-only class keyed by the file every TU saw, one
    `opq_t`, one `owrap`, both graphs referencing `c:include/opq.h::struct opq`. FFmpeg forward-declares its opaque
    types in several headers this way; without the rule `AVCodecContext` splits five ways by identical layouts."""
    proj = _project(tmp_path)
    ga, gb = _run(proj, "src/oa.c:oa"), _run(proj, "src/ob.c:ob")
    for g, fn in ((ga, "c:src/oa.c::oa"), (gb, "c:src/ob.c::ob")):
        assert g.nodes[fn].params[0].type_ref == "c:include/opq.h::struct owrap"
        assert g.types["c:include/opq.h::struct owrap"].fields[0].type_ref == "c:include/opq.h::opq_t"
        assert g.types["c:include/opq.h::opq_t"].underlying_ref == "c:include/opq.h::struct opq"
        assert g.types["c:include/opq.h::struct opq"].size is None
        assert not [t for t in g.types if "opaque" in t or "@" in t]
    assert not any("opq" in n or "owrap" in n for n in ga.meta["notes"] + gb.meta["notes"])


def test_redeclared_typedef_is_one_identity(tmp_path):
    """FFmpeg finding: `typedef struct rctx rctx_t;` appears in ctx_a.h and ctx_b.h; a TU's typedef USR names whichever
    header it saw first, so ra1.c and ra2.c would disagree on the identity of `holder.ctx` and split `holder`. The
    two declarations name one target, so they are one typedef keyed by the declaring file every TU saw."""
    proj = _project(tmp_path)
    g1, g2 = _run(proj, "src/ra1.c:ra1"), _run(proj, "src/ra2.c:ra2")
    for g, fn in ((g1, "c:src/ra1.c::ra1"), (g2, "c:src/ra2.c::ra2")):
        assert g.nodes[fn].params[0].type_ref == "c:include/ctx_a.h::struct holder"
        assert g.types["c:include/ctx_a.h::struct holder"].fields[0].type_ref == "c:include/ctx_a.h::rctx_t"
        assert g.types["c:include/ctx_a.h::rctx_t"].underlying_ref == "c:include/ctx_a.h::struct rctx"
        assert g.types["c:include/ctx_a.h::rctx_t"].loc.file == "include/ctx_a.h"
        assert not [t for t in g.types if "ctx_b" in t or "@" in t or "#" in t]
    assert not any("rctx" in n or "holder" in n for n in g1.meta["notes"] + g2.meta["notes"])
    strip = lambda g: {k: {f: v for f, v in t.items() if f != "used_by"} for k, t in _shape(g)["types"].items()}
    assert strip(g1) == strip(g2)


def test_truly_disconnected_opaque_declarations_stay_two_identities(tmp_path):
    """c_opaque.h and d_opaque.h each declare `struct opq2` with their own typedef and wrapper; no file names the tag
    in both TUs, so nothing links them: two identities, two typedefs, two wrappers, no variants, no note."""
    proj = _project(tmp_path)
    gc, gd = _run(proj, "src/oc.c:oc"), _run(proj, "src/od.c:od")
    assert gc.types["c:include/c_opaque.h::c_t"].underlying_ref == "c:include/c_opaque.h::struct opq2"
    assert gd.types["c:include/d_opaque.h::d_t"].underlying_ref == "c:include/d_opaque.h::struct opq2"
    assert "c:include/d_opaque.h::struct opq2" not in gc.types and "c:include/c_opaque.h::struct opq2" not in gd.types
    assert not [t for t in list(gc.types) + list(gd.types) if "@" in t]
    assert not any("opq2" in n for n in gc.meta["notes"] + gd.meta["notes"])


def test_local_stub_and_conditional_layout_survive_a_comment_shift(tmp_path):
    """Review round 11: the header-defined `lf` has a local stub `lf::lnode` and a local `lf::box` whose layout depends
    on -DWIDE, so the index holds two `box` variants pointing at one stub (a graph shows the owning TU's variant: a
    header function keeps one record). A function-local USR carries a byte offset, so a comment line above the
    function moves every offset; no id may move with it."""
    from hx.frontends.clang_fe import ClangFrontend
    proj = _project(tmp_path)

    def index():
        fe = ClangFrontend(str(proj), str(proj / "build"), jobs=1)
        fe.build_index()
        box = {tid: fe.types[k] for k, tid in fe.type_ids.items() if tid.startswith("c:include/lf.h::struct lf::box@")}
        return fe, box
    fe, box = index()
    wide, narrow = _gcc_run(proj, ["src/lf1.c"], ["lf1"], "-DWIDE")[0], _gcc_run(proj, ["src/lf2.c"], ["lf2"])[0]
    assert len(box) == 2 and sorted(t["size"] for t in box.values()) == sorted([wide, narrow]) and wide != narrow
    assert all(fe.type_ids[t["fields"][0]["type_usr"]] == "c:include/lf.h::struct lf::lnode" for t in box.values())
    assert any("struct lf::box: 2 different layouts/targets" in n for n in fe.notes)
    g = _run(proj, "src/lf1.c:lf1")
    assert _variants(g, "c:include/lf.h::struct lf::box@")[0] in box and g.types["c:include/lf.h::struct lf::lnode"].size is None
    before = (set(box), set(g.types), set(g.nodes), _shape_sans_loc(g))
    hdr = proj / "include" / "lf.h"
    hdr.write_text("/* a comment line: every byte offset below moves, no id may */\n" + hdr.read_text())
    fe2, box2 = index()
    assert fe2.stats["parsed"] >= 2                                                        # the header edit re-parsed both TUs
    g2 = _run(proj, "src/lf1.c:lf1")
    assert (set(box2), set(g2.types), set(g2.nodes), _shape_sans_loc(g2)) == before


def test_function_local_types_are_distinct(tmp_path):
    """Review round 9: `loc_f::local` (4 bytes) and `loc_g::local` (16 bytes) used to share one public id, so the graph
    kept one layout. Sizes come from the compiler calling the functions. Two `struct blk` in two blocks of one
    function are a residual collision: both kept, with a documented position-dependent #hash and a note."""
    proj = _project(tmp_path)
    gf, gg, gh = _run(proj, "src/l.c:loc_f"), _run(proj, "src/l.c:loc_g"), _run(proj, "src/l.c:loc_h")
    sf, sg = _gcc_run(proj, ["src/l.c"], ["loc_f", "loc_g"])
    assert gf.types["c:src/l.c::struct loc_f::local"].size == sf == 4
    assert gg.types["c:src/l.c::struct loc_g::local"].size == sg == 16
    assert "c:src/l.c::struct loc_g::local" not in gf.types and "c:src/l.c::struct loc_f::local" not in gg.types
    assert not [t for t in list(gf.types) + list(gg.types) if "local" in t and ("#" in t or "@" in t)]
    blk = sorted(t for t in gh.types if t.startswith("c:src/l.c::struct loc_h::blk#"))
    assert len(blk) == 2 and {gh.types[t].size for t in blk} == {1, 8} and "c:src/l.c::struct loc_h::blk" not in gh.types
    assert any("struct loc_h::blk: 2 distinct types share this id" in n for n in gh.meta["notes"])
    assert _shape(_run(proj, "src/l.c:loc_f")) == _shape(gf)                               # warm == cold


def test_cpp_local_classes_are_distinct(tmp_path):
    proj = tmp_path / "cpp_local"
    shutil.copytree(CPP, proj)
    _write_cc(proj, ["u1.cpp", "u2.cpp", "local.cpp"], compiler="g++")
    gf, gg = _run(proj, "src/local.cpp:f"), _run(proj, "src/local.cpp:g")
    sf, sg = _gcc_run(proj, ["src/local.cpp"], ["f", "g"], compiler="g++")
    assert gf.types["cpp:src/local.cpp::struct f::L"].size == sf == 4
    assert gg.types["cpp:src/local.cpp::struct g::L"].size == sg == 8
    assert "cpp:src/local.cpp::struct g::L" not in gf.types and "cpp:src/local.cpp::struct f::L" not in gg.types


def test_differing_layouts_in_one_declaration_file(tmp_path):
    proj = _project(tmp_path)
    g1, g2 = _run(proj, "src/w1.c:w1"), _run(proj, "src/w2.c:w2")
    c1, c2 = _variants(g1, "c:include/cfg.h::struct cfg@"), _variants(g2, "c:include/cfg.h::struct cfg@")
    assert len(c1) == len(c2) == 1 and c1 != c2
    wide, narrow = _gcc_sizeof(proj, ["cfg.h"], ["struct cfg"], "-DWIDE")[0], _gcc_sizeof(proj, ["cfg.h"], ["struct cfg"])[0]
    assert g1.types[c1[0]].size == wide and g2.types[c2[0]].size == narrow and wide != narrow
    assert [f.name for f in g1.types[c1[0]].fields] == ["a", "b", "c"] and [f.name for f in g2.types[c2[0]].fields] == ["a", "c"]
    assert any("struct cfg: 2 different layouts/targets" in n for n in g1.meta["notes"])


def test_enum_variants_by_enumerators(tmp_path):
    proj = _project(tmp_path)
    g1, g2 = _run(proj, "src/w1.c:w1"), _run(proj, "src/w2.c:w2")
    m1, m2 = _variants(g1, "c:include/cfg.h::enum mode@"), _variants(g2, "c:include/cfg.h::enum mode@")
    assert len(m1) == len(m2) == 1 and m1 != m2
    assert [e.name for e in g1.types[m1[0]].enumerators] == ["M_A", "M_B", "M_C"]
    assert [e.name for e in g2.types[m2[0]].enumerators] == ["M_A", "M_B"]


def test_recursive_type_fingerprints_are_canonical(tmp_path):
    proj = _project(tmp_path)
    g1, g2 = _run(proj, "src/r1.c:r1"), _run(proj, "src/r2.c:r2")
    for g in (g1, g2):
        assert g.types["c:include/ra.h::struct a"].fields[0].type_ref == "c:include/rb.h::struct b"
        assert g.types["c:include/rb.h::struct b"].fields[0].type_ref == "c:include/ra.h::struct a"
        assert not [t for t in g.types if t.startswith("c:include/r") and "@" in t]
    assert not any("struct a:" in n or "struct b:" in n for n in g1.meta["notes"])
    # a third TU that grows struct b: b and, through its edge, a get two layouts each
    grown = _project(tmp_path, ALL + ["r3.c"], name="grown")
    g3 = _run(grown, "src/r3.c:r3")
    assert len(_variants(g3, "c:include/rb.h::struct b@")) == 1 and len(_variants(g3, "c:include/ra.h::struct a@")) == 1
    g1b = _run(grown, "src/r1.c:r1")
    assert _variants(g1b, "c:include/rb.h::struct b@") != _variants(g3, "c:include/rb.h::struct b@")
    # the pure function: self and mutual recursion, unrelated records, input order
    def rec(name, edges, local=("s",)):
        return {"identity": ["struct", name, "inc/h.h"], "local": list(local), "edges": [list(e) for e in edges]}
    base = {"a": rec("a", [("f:b", "b")]), "b": rec("b", [("f:a", "a")]), "node": rec("node", [("f:next", "node")])}
    fp = ids.fingerprint_types(base)
    assert fp == ids.fingerprint_types(dict(reversed(list(base.items()))))
    with_extra = dict(base, extra=rec("extra", []), uses=rec("uses", [("f:x", "extra")]))
    assert {k: ids.fingerprint_types(with_extra)[k] for k in base} == fp
    changed = dict(base, b=rec("b", [("f:a", "a")], local=("s", "grown")))
    assert ids.fingerprint_types(changed)["b"] != fp["b"] and ids.fingerprint_types(changed)["a"] != fp["a"]
    assert ids.fingerprint_types(changed)["node"] == fp["node"]
    assert all(len(v) == 8 for v in fp.values()) and fp["a"] != fp["b"]


def test_separate_definitions_in_two_c_files_stay_distinct(tmp_path):
    proj = _project(tmp_path)
    g1, g2 = _run(proj, "src/s1.c:s1"), _run(proj, "src/s2.c:s2")
    assert set(g1.types) == {"c:src/s1.c::struct sa", "c:src/s1.c::struct sb"}
    assert set(g2.types) == {"c:src/s2.c::struct sa", "c:src/s2.c::struct sb"}
    assert not any("struct sa" in n or "struct sb" in n for n in g1.meta["notes"])


def test_qualified_identity_orders_scc_members(tmp_path):
    proj = tmp_path / "cpp_rec"
    shutil.copytree(CPP, proj)
    _write_cc(proj, ["u1.cpp", "u2.cpp"], compiler="g++")
    g1, g2 = _run(proj, "src/u1.cpp:u1"), _run(proj, "src/u2.cpp:u2")
    for g in (g1, g2):
        assert g.types["cpp:include/nodes.h::struct A::node"].fields[0].type_ref == "cpp:include/nodes.h::struct B::node"
        assert g.types["cpp:include/nodes.h::struct B::node"].fields[0].type_ref == "cpp:include/nodes.h::struct A::node"
        assert not [t for t in g.types if "node" in t and "@" in t]
    rec = lambda q, peer: {"identity": ["struct", q, "include/nodes.h"], "local": ["s"], "edges": [["f:peer", peer]]}
    fwd = {"A::node": rec("A::node", "B::node"), "B::node": rec("B::node", "A::node")}
    rev = dict(reversed(list(fwd.items())))
    assert ids.fingerprint_types(fwd) == ids.fingerprint_types(rev) and ids.fingerprint_types(fwd)["A::node"] != ids.fingerprint_types(fwd)["B::node"]


def test_variant_ids_survive_relocation(tmp_path):
    p1 = _project(tmp_path, name="here")
    p2 = _project(tmp_path / "elsewhere" / "deeper", name="moved")
    for entry in ("src/d1.c:d1", "src/w1.c:w1", "src/r1.c:r1", "src/a/options.c:run_a"):
        a, b = _run(p1, entry), _run(p2, entry)
        assert set(a.types) == set(b.types) and set(a.nodes) == set(b.nodes) and _shape(a) == _shape(b), entry


def test_symlinked_source_dir_yields_relative_ids(tmp_path):
    """Review finding C4: a compile command that reaches the source through a symlink must give the same ids as one
    that names the real path."""
    proj = _project(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(proj / "src", target_is_directory=True)
    direct = _shape(_run(proj, "src/a/options.c:run_a"))
    cc = [{"directory": str(proj), "file": f"../link/{f}", "command": f"gcc -Iinclude -c ../link/{f} -o build/{f.replace('/', '_')}.o"}
          for f in ALL]
    (proj / "build" / "compile_commands.json").write_text(json.dumps(cc))
    g = _run(proj, "src/a/options.c:run_a", use_cache=False)
    assert g.entry == "c:src/a/options.c::run_a" and not any(i.startswith("c:/") for i in g.nodes)
    assert _shape(g) == direct
    g2 = _run(proj, str(link / "a" / "options.c") + ":run_a", use_cache=False)                 # entry spelled through the link
    assert g2.entry == "c:src/a/options.c::run_a" and _shape(g2) == direct


def test_older_summaries_are_ignored(tmp_path):
    """Seeding the cache with an entry stored under the previous SUMMARY_VERSION proves that the current extraction
    never consults it (clearing the cache would prove nothing)."""
    from hx import __version__
    from hx.cache import TUCache
    from hx.frontends.clang_fe import ClangFrontend, SUMMARY_VERSION, _libclang_version, load_jobs
    proj = _project(tmp_path, ["t3.c"])
    fe = ClangFrontend(str(proj), str(proj / "build"), jobs=1)
    job = load_jobs(str(proj / "build"), [], fe.resource_dir)[0]
    old_extra = (SUMMARY_VERSION - 1, fe.root, 0, __version__, _libclang_version(), os.environ.get("HX_LIBCLANG", ""))
    assert SUMMARY_VERSION == 5 and old_extra[0] != fe._cache_extra()[0] and old_extra[1:] == fe._cache_extra()[1:]
    sentinel = {"file": job.file, "lang": "c", "functions": {"c:@F@SENTINEL": {"name": "SENTINEL"}}, "decls": {}, "vars": {},
                "types": {}, "deps": TUCache.snapshot_deps([job.file]), "diagnostics": [], "n_errors": 0}
    TUCache(str(proj / ".hx" / "cache")).store(job.file, job.args, sentinel, old_extra)
    g = _run(proj, "src/t3.c:f3")
    assert g.meta["index"]["cached"] == 0 and g.meta["index"]["parsed"] == 1
    assert not any(n.name == "SENTINEL" for n in g.nodes.values())
