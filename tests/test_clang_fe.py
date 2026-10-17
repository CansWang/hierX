"""End-to-end checks of the libclang frontend on the fixture project."""
import os
import time

import pytest

ENTRY = "c:src/main.c::app_run"


def by_name(g):
    return {n.name: n for n in g.nodes.values()}


def edges(g, kind=None):
    return [e for e in g.edges if kind is None or e.kind == kind]


def test_nodes_and_depths(extract):
    g = extract(depth=3)
    n = by_name(g)
    assert g.entry == ENTRY
    assert {k: v.depth for k, v in n.items()} == {
        "app_run": 0, "dma_start": 1, "dma_poll": 1, "on_done": 1,
        "dma_prog_desc": 2, "hal_write32": 2, "hal_read32": 2, "hal_write_block": 3,
    }
    assert n["dma_prog_desc"].storage == "static" and n["dma_start"].storage == "extern"
    assert n["dma_prog_desc"].id == "c:src/dma.c::dma_prog_desc"
    assert n["hal_write32"].loc.file == "src/hal.c" and n["hal_write32"].loc.end_line > n["hal_write32"].loc.line
    assert n["dma_poll"].signature == "enum dma_status dma_poll(dma_chan_t * ch)"
    assert n["hal_read32"].signature == "uint32_t hal_read32(const volatile uint32_t * addr)"
    assert all(x.precision == "exact" for x in g.nodes.values())
    assert g.meta["index"]["diagnostics"] == 0, g.meta


def test_edge_kinds_and_args(extract):
    g = extract(depth=3)
    calls = {(e.src, e.dst, e.kind) for e in g.edges}
    assert ("c:src/main.c::app_run", "c:src/dma.c::dma_start", "call") in calls
    assert ("c:src/main.c::app_run", "c:src/dma.c::dma_poll", "call") in calls
    assert ("c:src/main.c::app_run", "c:src/main.c::on_done", "ref") in calls
    assert ("c:src/main.c::app_run", "c:include/hal.h::hal_board_init", "call") in calls
    assert ("c:src/dma.c::dma_start", "c:src/dma.c::dma_prog_desc", "call") in calls
    assert ("c:src/dma.c::dma_start", "c:src/hal.c::hal_write32", "call") in calls
    assert ("c:src/dma.c::dma_prog_desc", "c:src/hal.c::hal_write32", "macro") in calls
    macro_edges = [e for e in edges(g, "macro")]
    assert len(macro_edges) == 2 and all(e.macro == "HAL_WRITE32" for e in macro_edges)
    assert macro_edges[0].args == ["ch->base", "ch->desc.src"]
    start_edge = next(e for e in g.edges if e.dst == "c:src/dma.c::dma_start")
    assert start_edge.args == ["&ch", "data", "n"] and start_edge.loc.file == "src/main.c"
    fp = edges(g, "fnptr")
    assert len(fp) == 2 and all(e.dst is None and e.name == "ch->cb" for e in fp)
    assert fp[0].ptr_type == "dma_cb_t"
    assert sorted(by_name(g)["dma_start"].calls) == sorted([
        "c:src/dma.c::dma_prog_desc", "c:src/hal.c::hal_write32"])


def test_unresolved(extract):
    g = extract(depth=3)
    reasons = {(u.name, u.reason) for u in g.unresolved}
    assert ("hal_board_init", "no definition in TU set") in reasons
    assert ("ch->cb", "indirect call through function pointer") in reasons
    hb = next(u for u in g.unresolved if u.name == "hal_board_init")
    assert hb.id == "c:include/hal.h::hal_board_init" and hb.src == ENTRY
    g1 = extract(depth=1)
    assert set(by_name(g1)) == {"app_run", "dma_start", "dma_poll", "on_done"}
    assert {u.name for u in g1.unresolved if u.reason == "beyond depth limit"} == {"dma_prog_desc", "hal_write32", "hal_read32"}


def test_param_direction_heuristic(extract):
    g = extract(depth=3)
    n = by_name(g)
    dirs = {p.name: p.dir for p in n["dma_start"].params}
    assert dirs == {"ch": "inout", "buf": "in", "len": "in"}
    assert all(p.dir_source == "heuristic" for p in n["dma_start"].params)
    assert [p.dir for p in n["hal_write32"].params] == ["inout", "in"]
    assert [p.dir for p in n["hal_read32"].params] == ["in"]
    assert [p.dir for p in n["hal_write_block"].params] == ["inout", "in", "in"]   # const uint32_t words[] is in
    assert n["hal_write_block"].params[1].type == "const uint32_t[]"
    assert [p.dir for p in n["on_done"].params] == ["inout", "in"]  # void* ctx: non-const pointer
    assert n["dma_start"].params[0].type_ref == "c:include/dma.h::dma_chan_t"
    assert n["dma_start"].params[1].type_ref == "c:/usr/include/x86_64-linux-gnu/bits/stdint-uintn.h::uint8_t" or \
        n["dma_start"].params[1].type_ref.endswith("::uint8_t")
    assert n["dma_poll"].returns.type_ref == "c:include/dma.h::enum dma_status"


def test_struct_layout_matches_compiler(extract, layout_probe):
    g = extract(depth=3)
    chan_td = g.types["c:include/dma.h::dma_chan_t"]
    assert chan_td.kind == "typedef" and chan_td.underlying_ref == "c:include/dma.h::struct dma_chan"
    chan = g.types["c:include/dma.h::struct dma_chan"]
    truth = layout_probe["struct dma_chan"]
    assert chan.size == truth["size"] and chan.align == 8
    offs = {f.name: f.offset for f in chan.fields}
    for fname in ("base", "desc", "cb", "cb_ctx", "stat"):
        assert offs[fname] == truth[fname], fname
    bits = {f.name: f for f in chan.fields if f.bit_width}
    assert bits["busy"].bit_width == 1 and bits["busy"].bit_offset == 0 and bits["busy"].size is None
    assert bits["prio"].bit_width == 3 and bits["prio"].bit_offset == 1 and bits["prio"].offset == offs["cb_ctx"] + 8
    desc = g.types["c:include/dma.h::struct dma_desc"]
    truth = layout_probe["struct dma_desc"]
    assert desc.size == truth["size"]
    assert [(f.name, f.offset, f.size) for f in desc.fields] == [
        ("src", truth["src"], 4), ("dst", truth["dst"], 4), ("len", truth["len"], 2), ("flags", truth["flags"], 1)]
    stat = next(f for f in chan.fields if f.name == "stat")
    anon = g.types[stat.type_ref]
    assert anon.kind == "union" and anon.anonymous and anon.id == "c:include/dma.h::union dma_chan.stat"   # named by parent.member: survives line shifts
    assert [f.name for f in anon.fields] == ["raw", "bytes"]
    inner = g.types[next(f for f in anon.fields if f.name == "bytes").type_ref]
    assert [f.name for f in inner.fields] == ["a", "b", "c", "d"] and inner.size == 4
    assert inner.id == "c:include/dma.h::struct dma_chan.stat.bytes"
    anon_member = [f for f in chan.fields if f.name == ""]
    assert len(anon_member) == 1 and anon_member[0].type == "struct (anonymous)"
    hdr = g.types[anon_member[0].type_ref]
    assert hdr.anonymous and [f.name for f in hdr.fields] == ["head", "tail"] and hdr.size == 4
    assert hdr.id == "c:include/dma.h::struct dma_chan.(anon#7)"
    assert anon_member[0].offset == layout_probe["struct dma_chan"]["head"]
    cb = g.types["c:include/dma.h::dma_cb_t"]
    assert cb.kind == "typedef" and cb.underlying == "void (*)(void *, int)" and cb.underlying_ref is None
    st = g.types["c:include/dma.h::enum dma_status"]
    assert [(e.name, e.value) for e in st.enumerators] == [("DMA_OK", 0), ("DMA_BUSY", -1), ("DMA_ERR", -2)]
    assert "c:src/dma.c::dma_start" in chan_td.used_by and ENTRY in chan_td.used_by  # app_run via its static ch
    u8 = g.types[next(t for t in g.types if t.endswith("::uint8_t"))]
    assert u8.system and u8.kind == "typedef"


def test_type_depth_limits_nesting(extract):
    g = extract(depth=3, type_depth=0)
    assert "c:include/dma.h::dma_chan_t" in g.types
    assert "c:include/dma.h::struct dma_chan" in g.types          # typedef alias is free
    assert "c:include/dma.h::struct dma_desc" not in g.types       # a field type: level 1
    g = extract(depth=3, type_depth=1)
    assert "c:include/dma.h::struct dma_desc" in g.types
    anon_union = next(t for t in g.types.values() if t.kind == "union")
    inner_ref = next(f for f in anon_union.fields if f.name == "bytes").type_ref
    assert inner_ref not in g.types                                # level 2


def test_globals_read_write(extract):
    g = extract(depth=3)
    n = by_name(g)
    gs = n["dma_start"].globals
    assert gs.reads == ["c:src/dma.c::g_dma_active", "c:src/dma.c::g_dma_max"]
    assert gs.writes == ["c:src/dma.c::g_dma_active"]
    assert n["dma_prog_desc"].globals.reads == [] and n["dma_prog_desc"].globals.writes == []
    poll = n["dma_poll"].globals
    assert "c:src/dma.c::g_dma_errors" in poll.writes and "c:src/dma.c::g_dma_errors" in poll.reads   # via macro
    assert "c:src/dma.c::g_dma_active" in poll.writes
    assert n["on_done"].globals.writes == ["c:src/main.c::g_done_count"]
    ar = n["app_run"].globals
    assert "c:src/main.c::app_run.ch" in ar.writes            # &ch passed out, ch.cb assigned
    gv = g.globals["c:src/main.c::app_run.ch"]
    assert gv.scope == "function-static" and gv.type_ref == "c:include/dma.h::dma_chan_t"
    assert g.globals["c:src/dma.c::g_dma_max"].storage == "static"


def test_ids_stable_under_whitespace_edit_hash_changes_on_real_edit(extract, cproj):
    g0 = extract(depth=3)
    dma_c = cproj / "src" / "dma.c"
    src = dma_c.read_text()
    dma_c.write_text(src.replace("    g_dma_active++;\n", "\n\n    g_dma_active++;   \n"))
    os.utime(dma_c, (time.time() + 2, time.time() + 2))
    g1 = extract(depth=3)
    assert set(g1.nodes) == set(g0.nodes)
    assert g1.nodes["c:src/dma.c::dma_start"].body_hash == g0.nodes["c:src/dma.c::dma_start"].body_hash
    dma_c.write_text(src.replace("hal_write32(ch->base + 2, 1u);", "hal_write32(ch->base + 2, 2u);"))
    os.utime(dma_c, (time.time() + 4, time.time() + 4))
    g2 = extract(depth=3)
    assert set(g2.nodes) == set(g0.nodes)
    assert g2.nodes["c:src/dma.c::dma_start"].body_hash != g0.nodes["c:src/dma.c::dma_start"].body_hash
    assert g2.nodes["c:src/dma.c::dma_poll"].body_hash == g0.nodes["c:src/dma.c::dma_poll"].body_hash
    assert g2.nodes["c:src/dma.c::dma_start"].signature == g0.nodes["c:src/dma.c::dma_start"].signature


def test_cache_hits_and_invalidation(extract, cproj):
    g0 = extract(depth=1)
    assert g0.meta["index"]["cached"] == 0 and g0.meta["index"]["parsed"] == 3
    g1 = extract(depth=1)
    assert g1.meta["index"]["cached"] == 3 and g1.meta["index"]["parsed"] == 0
    hal_h = cproj / "include" / "hal.h"
    hal_h.write_text(hal_h.read_text() + "\n/* touched */\n")
    os.utime(hal_h, (time.time() + 2, time.time() + 2))
    g2 = extract(depth=1)
    assert g2.meta["index"]["parsed"] == 3   # every TU includes hal.h
    assert g2.nodes == g1.nodes
    g3 = extract(depth=1, use_cache=False)
    assert g3.meta["index"]["cached"] == 0


def test_include_callers(extract):
    g = extract("src/hal.c:hal_write32", depth=1, include_callers=True)
    n = by_name(g)
    assert {k: v.depth for k, v in n.items()} == {"hal_write32": 0, "dma_start": -1, "dma_prog_desc": -1}
    assert all(e.dst == "c:src/hal.c::hal_write32" for e in g.edges)
    g = extract("src/hal.c:hal_write32", depth=2, include_callers=True)
    assert by_name(g)["app_run"].depth == -2
    g = extract("include/hal.h:hal_write32", depth=0)   # entry given via the header that declares it
    assert g.entry == "c:src/hal.c::hal_write32"


def test_entry_errors(extract):
    from hx.frontends.base import EntryNotFound
    with pytest.raises(EntryNotFound) as ei:
        extract("src/main.c:app_rnu")
    assert "app_run" in ei.value.suggestions
    with pytest.raises(EntryNotFound):
        extract("src/nothere.c:foo")


def test_parallel_matches_serial(extract):
    a = extract(depth=3, jobs=1, use_cache=False).to_dict()
    b = extract(depth=3, jobs=3, use_cache=False).to_dict()
    for k in ("nodes", "types", "globals", "edges", "unresolved"):
        assert a[k] == b[k], k


def test_entry_in_other_file_is_noted(extract):
    g = extract("src/main.c:hal_write32", depth=0)   # defined in src/hal.c, not even declared via main.c
    assert g.entry == "c:src/hal.c::hal_write32"
    assert g.meta["notes"] == ["'hal_write32' is not defined in src/main.c; using its definition in src/hal.c"]


def test_comment_only_edit_keeps_body_hash(extract, cproj):
    g0 = extract(depth=2)
    dma_c = cproj / "src" / "dma.c"
    src = dma_c.read_text()
    assert "    ch->busy = 1;\n" in src
    dma_c.write_text(src.replace("    ch->busy = 1;\n", "    ch->busy = 1; /* agent: mark busy */\n    // (comment-only edit)\n", 1))
    g1 = extract(depth=2)
    assert g1.nodes["c:src/dma.c::dma_start"].body_hash == g0.nodes["c:src/dma.c::dma_start"].body_hash
    dma_c.write_text(src.replace("    ch->busy = 1;\n", "    ch->busy = 2;\n", 1))
    g2 = extract(depth=2)
    assert g2.nodes["c:src/dma.c::dma_start"].body_hash != g0.nodes["c:src/dma.c::dma_start"].body_hash


def _shape(g):
    """Everything in a graph that must not depend on cache state."""
    d = g.to_dict()
    return {"nodes": {k: {kk: vv for kk, vv in v.items() if kk != "depth" or True} for k, v in d["nodes"].items()},
            "types": d["types"], "globals": d["globals"],
            "edges": sorted((e["from"], e.get("to") or "", e["kind"], tuple(e.get("args") or [])) for e in d["edges"]),
            "unresolved": sorted((u["name"], u["from"], u["reason"]) for u in d["unresolved"])}


def test_index_is_independent_of_cache_state(tmp_path):
    """Review finding H3: a header-defined inline function compiled under different macros must resolve to the
    same build variant whether the TUs come from the cache or a fresh parse, and hx must report the ambiguity."""
    import json
    import shutil
    import time
    from hx.api import extract as _extract
    src = os.path.join(os.path.dirname(__file__), "fixtures", "c_variants")
    proj = tmp_path / "variants"
    shutil.copytree(src, proj, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
    (proj / "build").mkdir()
    cc = [{"directory": str(proj), "file": f"src/{f}", "command": f"gcc -Iinclude {d} -c src/{f} -o build/{f}.o"}
          for f, d in (("a.c", "-DUSE_FA"), ("b.c", "-DUSE_FB"), ("impl.c", ""))]
    (proj / "build" / "compile_commands.json").write_text(json.dumps(cc))

    def run(**kw):
        kw.setdefault("jobs", 1)
        return _extract("src/a.c:run_a", root=str(proj), depth=3, **kw)

    def touch(name):
        time.sleep(0.01)
        p = proj / "src" / name
        p.write_text(p.read_text())
        os.utime(p, None)

    cold = run()
    edges = {(e.src.split("::")[1], (e.dst or "").split("::")[-1]) for e in cold.edges}
    assert ("helper", "fa") in edges and ("helper", "fb") not in edges, edges   # TU order a.c < b.c → a.c's variant
    assert any("helper: compiled differently in 2 build variants" in n for n in cold.meta.get("notes", [])), cold.meta
    assert cold.meta["index"]["variants"] == 1
    warm = run()
    assert warm.meta["index"]["cached"] == 3 and _shape(warm) == _shape(cold)
    touch("b.c")                                   # the reviewer's reproduction: touching the *other* TU flipped helper → fb
    partial = run()
    assert partial.meta["index"]["parsed"] == 1 and _shape(partial) == _shape(cold)
    touch("a.c")
    assert _shape(run()) == _shape(cold)
    nocache = run(use_cache=False)
    assert _shape(nocache) == _shape(cold)


def test_include_system_is_part_of_the_cache_key(extract):
    g_off = extract(depth=2)                                   # populates the cache with include_system=False summaries
    g_on_warm = extract(depth=2, include_system=True)
    g_on_cold = extract(depth=2, include_system=True, use_cache=False)
    assert g_on_warm.meta["index"]["cached"] == 0              # different key → nothing reused from the other mode
    assert set(g_on_warm.nodes) == set(g_on_cold.nodes) and set(g_on_warm.types) == set(g_on_cold.types)
    assert set(g_on_cold.types) >= set(g_off.types)


def _cpp_project(tmp_path):
    import json
    import shutil
    src = os.path.join(os.path.dirname(__file__), "fixtures", "cpp")
    proj = tmp_path / "cpp"
    shutil.copytree(src, proj, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
    (proj / "build").mkdir()
    cc = [{"directory": str(proj), "file": f"src/{f}", "command": f"g++ -std=c++17 -Iinclude -c src/{f} -o build/{f}.o"} for f in ("bus.cpp", "main.cpp")]
    (proj / "build" / "compile_commands.json").write_text(json.dumps(cc))
    return proj


def test_cpp_overload_ids_do_not_depend_on_siblings(tmp_path):
    from hx.api import extract as _extract
    proj = _cpp_project(tmp_path)
    g = _extract("src/main.cpp:run", root=str(proj), depth=3, jobs=1)
    ids = {n.qualname + "|" + n.signature: n.id for n in g.nodes.values()}
    writes = sorted(i for i in g.nodes if "::hw::Bus::write(" in i)
    assert writes == ["cpp:src/bus.cpp::hw::Bus::write(const Reg &)", "cpp:src/bus.cpp::hw::Bus::write(const uint8_t *, size_t)",
                      "cpp:src/bus.cpp::hw::Bus::write(uint32_t, uint32_t)"], writes
    assert "cpp:src/bus.cpp::hw::Bus::read(uint32_t)" in g.nodes and g.entry == "cpp:src/main.cpp::hw::run(Bus &)"   # spelled as written in scope
    assert not any("#" in i for i in g.nodes)                                   # readable, no hash suffixes needed
    tmpl = [i for i in g.nodes if "clamp" in i]
    assert tmpl and tmpl[0].startswith("cpp:include/bus.hpp::hw::clamp(")
    before = set(g.nodes)
    # add a 4th overload: existing ids must be unchanged (annotations keep pointing at the same symbols)
    hpp = proj / "include" / "bus.hpp"
    hpp.write_text(hpp.read_text().replace("    uint32_t read(uint32_t addr) const;", "    int write(bool flag);\n    uint32_t read(uint32_t addr) const;"))
    cpp = proj / "src" / "bus.cpp"
    cpp.write_text(cpp.read_text().replace("uint32_t Bus::read(", "int Bus::write(bool flag) { return write(0u, flag ? 1u : 0u); }\n\nuint32_t Bus::read("))
    g2 = _extract("src/main.cpp:run", root=str(proj), depth=3, jobs=1)
    assert before <= set(g2.nodes) | {u.id for u in g2.unresolved}
    assert all(i in g2.nodes for i in writes)


def test_cross_compiler_args_probe_the_toolchain_for_its_system_includes(tmp_path, monkeypatch):
    from hx.frontends.clang_fe import cross_compiler_args
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "arm-none-eabi-gcc"
    fake.write_text("#!/bin/sh\n"
                    "echo '#include <...> search starts here:' >&2\n"
                    "echo ' /opt/arm/include' >&2\necho ' /opt/arm/lib/gcc/include' >&2\n"
                    "echo 'End of search list.' >&2\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    args = cross_compiler_args("arm-none-eabi-gcc", "c")
    assert args == ["--target=arm-none-eabi", "-isystem", "/opt/arm/include", "-isystem", "/opt/arm/lib/gcc/include"]
    assert cross_compiler_args("arm-none-eabi-gcc", "c") is args                    # memoised per (compiler, lang)
    assert cross_compiler_args("gcc", "c") == [] and cross_compiler_args("/usr/bin/cc", "cpp") == []
    assert cross_compiler_args("riscv64-unknown-elf-clang", "c") == ["--target=riscv64-unknown-elf"]   # clang: no include probe
