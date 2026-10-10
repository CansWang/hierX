"""CVA6-review regressions on tests/fixtures/sv_adv: wide parameters, generate scopes, specialized types,
anonymous port types, warnings, entry validation, cache identity (Phase 4.6)."""
import json
import os
import shutil
import sys

import pytest

from hx import values as V
from hx.frontends.base import EntryNotFound, FrontendError
from hx.frontends.verilator_fe import VerilatorFrontend
from hx.traverse import TraverseOptions, extract_graph

pytestmark = pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
FIX = os.path.join(os.path.dirname(__file__), "fixtures", "sv_adv")
TOP = "sv:rtl/top_adv.sv::top_adv"


@pytest.fixture
def adv(tmp_path):
    dst = tmp_path / "adv"
    shutil.copytree(FIX, dst, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
    return dst


def run(root, symbol="top_adv", file="rtl/top_adv.sv", filelist="files.f", depth=4, **fe_kw):
    fe = VerilatorFrontend(str(root), filelist=str(root / filelist), top="top_adv", **fe_kw)
    fe.build_index()
    return fe, extract_graph(fe, file, symbol, TraverseOptions(depth=depth, type_depth=3), str(root))


def shape(g):
    d = g.to_dict()
    return {"nodes": d["nodes"], "types": d["types"], "edges": sorted((e["from"], e.get("to") or "", e["kind"], tuple(e["args"])) for e in d["edges"]),
            "unresolved": sorted((u["name"], u["from"], u["reason"]) for u in d["unresolved"])}


# ---------------------------------------------------------------- H1 wide constants
def test_wide_parameter_is_lossless_compact_and_json_safe(adv, tmp_path):
    assert sys.get_int_max_str_digits() == 4300          # the default limit stays in force: the old code crashed under it
    fe, g = run(adv)
    top = g.nodes[TOP]
    cfg = top.attrs["parameters"]["CFG"]
    assert isinstance(cfg, str) and cfg == "16384'h" + "f" * 4096          # lossless canonical literal
    assert V.parse(cfg).int == (1 << 16384) - 1 and V.parse(cfg).width == 16384
    assert "CFG=16384'hffffffff…ffff" in top.signature and len(top.signature) < 200
    assert top.attrs["parameters"]["NLANES"] == 2
    p = tmp_path / "g.json"
    g.save(str(p))
    txt = p.read_text()
    assert "16384'h" in txt and not any(len(tok) > 16 for tok in __import__("re").findall(r"(?<![\w'\"])\d{17,}(?![\w'\"])", txt))
    from hx.model import Graph
    assert Graph.load(str(p)).nodes[TOP].attrs["parameters"]["CFG"] == cfg
    enc = json.loads(txt)                                 # a plain json.loads must not meet a wide number either
    assert enc["nodes"][TOP]["attrs"]["parameters"]["CFG"] == cfg


def test_wide_values_identical_across_cold_warm_and_no_cache(adv):
    _, cold = run(adv)
    fe2, warm = run(adv)
    assert fe2.stats["cached"] == 1
    _, nocache = run(adv, use_cache=False)
    assert shape(cold) == shape(warm) == shape(nocache)


# ---------------------------------------------------------------- H3 specialized types
def fp_types(g):
    return {tid: t for tid, t in g.types.items() if tid.startswith("sv:rtl/fp.sv::struct fp.fp_t@")}


def test_two_specializations_have_two_layout_identified_types(adv):
    _, g = run(adv)
    fps = fp_types(g)
    assert len(fps) == 2, sorted(g.types)
    by_size = {t.size: t for t in fps.values()}
    assert set(by_size) == {32, 64}
    assert [f.bit_width for f in by_size[32].fields] == [1, 8, 23] and [f.bit_width for f in by_size[64].fields] == [1, 11, 52]
    assert by_size[32].used_by == ["sv:rtl/fp.sv::top_adv.u_fp32"] and by_size[64].used_by == ["sv:rtl/fp.sv::top_adv.u_fp64"]
    assert "sv:rtl/adv_pkg.sv::struct adv_pkg::req_t" in g.types               # package-scoped types keep the bare id
    assert "sv:rtl/adv_pkg.sv::enum adv_pkg::st_t" in g.types
    assert {e.name: e.value for e in g.types["sv:rtl/adv_pkg.sv::enum adv_pkg::st_t"].enumerators} == {"S_IDLE": 0, "S_RUN": 1, "S_DONE": 2}


def test_type_ids_are_independent_of_siblings_and_order(adv):
    _, g0 = run(adv)
    ids0 = set(fp_types(g0))
    top = adv / "rtl" / "top_adv.sv"
    src = top.read_text()
    # (b) a THIRD specialization with an equal-size (32-bit) but different layout: existing ids unchanged
    top.write_text(src.replace("  fp #(.E(11), .M(52)) u_fp64 (.clk(clk), .in_bits(f64_i), .out_bits(f64_o));",
                               "  fp #(.E(11), .M(52)) u_fp64 (.clk(clk), .in_bits(f64_i), .out_bits(f64_o));\n"
                               "  logic [31:0] f32b_o;\n  fp #(.E(11), .M(20)) u_fp32b (.clk(clk), .in_bits(f32_i), .out_bits(f32b_o));"))
    _, g1 = run(adv)
    ids1 = set(fp_types(g1))
    assert ids0 < ids1 and len(ids1) == 3
    sizes = sorted(t.size for t in fp_types(g1).values())
    assert sizes == [32, 32, 64]
    # (c) declaration order swapped: ids unchanged
    top.write_text(src.replace("  fp #(.E(8),  .M(23)) u_fp32 (.clk(clk), .in_bits(f32_i), .out_bits(f32_o));\n"
                               "  fp #(.E(11), .M(52)) u_fp64 (.clk(clk), .in_bits(f64_i), .out_bits(f64_o));",
                               "  fp #(.E(11), .M(52)) u_fp64 (.clk(clk), .in_bits(f64_i), .out_bits(f64_o));\n"
                               "  fp #(.E(8),  .M(23)) u_fp32 (.clk(clk), .in_bits(f32_i), .out_bits(f32_o));"))
    _, g2 = run(adv)
    assert set(fp_types(g2)) == ids0
    # (d) signedness is part of the layout
    fp_sv = adv / "rtl" / "fp.sv"
    top.write_text(src)
    fp_sv.write_text(fp_sv.read_text().replace("    logic [M-1:0] mantissa;", "    logic signed [M-1:0] mantissa;"))
    _, g3 = run(adv)
    assert set(fp_types(g3)).isdisjoint(ids0) and len(fp_types(g3)) == 2


def test_field_edit_shows_as_one_changed_type(adv):
    from hx.diff import diff_graphs, render_markdown
    _, g0 = run(adv)
    fp_sv = adv / "rtl" / "fp.sv"
    fp_sv.write_text(fp_sv.read_text().replace("    logic [M-1:0] mantissa;\n", "    logic [M-1:0] mantissa;\n    logic         sticky;\n"))
    _, g1 = run(adv)
    d = diff_graphs(g0.to_dict(), g1.to_dict())
    assert d["summary"]["types_added"] == 0 and d["summary"]["types_removed"] == 0 and d["summary"]["types_changed"] == 2
    md = render_markdown(d, g1.to_dict())
    assert "fp.fp_t" in md and "+field sticky" in md and "layout changed" in md


# ---------------------------------------------------------------- H4 / H10 generated instances and spelling
def test_generated_instances_have_locations_and_connections(adv):
    _, g = run(adv)
    inst_edges = [e for e in g.edges if e.kind == "instance"]
    assert len(inst_edges) == 5 == len([n for n in g.nodes.values() if n.kind == "instance"])
    assert all(e.loc and e.loc.line > 0 for e in inst_edges)
    assert not any("…" in a for e in inst_edges for a in e.args), [e.args for e in inst_edges]
    by_dst = {e.dst: e for e in inst_edges}
    lane0 = "sv:rtl/lane.sv::top_adv.gen_lane[0].u_lane"
    assert lane0 in g.nodes and "sv:rtl/lane.sv::top_adv.gen_lane[1].u_lane" in g.nodes and "sv:rtl/lane.sv::top_adv.gen_multi.u_lane_star" in g.nodes
    assert by_dst[lane0].args == [".clk(clk)", ".rst_n(rst_n)", ".d_i(d_i + 8'(i))", ".q_o(lane_q[i])"]
    assert by_dst["sv:rtl/lane.sv::top_adv.gen_multi.u_lane_star"].args == [".clk(.*)", ".rst_n(.*)", ".d_i(.*)", ".q_o(.*)"]
    assert g.nodes[lane0].qualname == "top_adv.gen_lane[0].u_lane" and "__BRA__" not in json.dumps(g.to_dict())
    assert "sv:rtl/fp.sv::top_adv.u_fp32" in by_dst and by_dst["sv:rtl/fp.sv::top_adv.u_fp32"].args[1] == ".in_bits(f32_i)"


def test_generate_array_entry_accepts_both_spellings(adv):
    for sym in ("top_adv.gen_lane[1].u_lane", "top_adv.gen_lane__BRA__1__KET__.u_lane"):
        _, g = run(adv, symbol=sym, file="rtl/lane.sv", depth=0)
        assert g.entry == "sv:rtl/lane.sv::top_adv.gen_lane[1].u_lane"


# ---------------------------------------------------------------- H6 anonymous types, H7 ranges
def test_anonymous_port_type_named_by_context_and_stable_under_comments(adv):
    from hx.diff import diff_graphs
    _, g0 = run(adv)
    anon = [t for t in g0.types if "::struct top_adv.cfg_i@" in t]
    assert len(anon) == 1, sorted(g0.types)
    assert [f.name for f in g0.types[anon[0]].fields] == ["a", "b"] and g0.types[anon[0]].size == 12
    assert not any("anon@L" in t or "__typeimp" in t for t in g0.types)
    top = adv / "rtl" / "top_adv.sv"
    top.write_text("// a comment line that shifts every line number\n\n" + top.read_text())
    _, g1 = run(adv)
    assert set(g1.types) == set(g0.types) and set(g1.nodes) == set(g0.nodes)
    d = diff_graphs(g0.to_dict(), g1.to_dict())
    assert d["summary"]["any"] is False, d["summary"]


def test_module_ranges_cover_the_whole_definition(adv):
    _, g = run(adv)
    lines = (adv / "rtl" / "top_adv.sv").read_text().splitlines()
    top = g.nodes[TOP]
    assert top.loc.end_line == len(lines) and lines[top.loc.end_line - 1].startswith("endmodule")
    fp = g.nodes["sv:rtl/fp.sv::top_adv.u_fp32"]
    fp_lines = (adv / "rtl" / "fp.sv").read_text().splitlines()
    assert fp.loc.end_line == len(fp_lines) and fp.loc.end_line > fp.loc.line
    for n in g.nodes.values():
        assert n.loc.end_line is None or n.loc.end_line >= n.loc.line


# ---------------------------------------------------------------- H8 warnings
def test_warnings_are_kept_and_counted_separately(adv):
    fe, g = run(adv)
    assert fe.stats["diagnostics"] == 0 and fe.stats["warnings"] == 2
    assert fe.stats["warnings_by_tag"] == {"SELRANGE": 1, "WIDTHCONCAT": 1} or set(fe.stats["warnings_by_tag"]) == {"SELRANGE", "WIDTHCONCAT"}
    assert any(n.startswith("verilator: 2 warning(s)") for n in fe.notes)
    sel = [w for w in fe.idx["warnings"] if w["tag"] == "SELRANGE"][0]
    assert sel["file"].endswith("rtl/top_adv.sv") and sel["line"] == 24 and "out of range" in sel["message"]
    fe2, _ = run(adv)                                    # cached run: warnings come back from the index
    assert fe2.stats["cached"] == 1 and fe2.stats["warnings"] == 2


# ---------------------------------------------------------------- H9 entry validation
def test_entry_file_must_define_the_symbol(adv):
    with pytest.raises(EntryNotFound) as ei:
        run(adv, file="rtl/not-a-real-file.sv")
    assert "rtl/top_adv.sv" in str(ei.value) and "not part of the elaborated design" in str(ei.value)
    with pytest.raises(EntryNotFound) as ei:
        run(adv, file="rtl/lane.sv")
    assert "rtl/top_adv.sv" in str(ei.value) and "rtl/lane.sv" in str(ei.value)
    with pytest.raises(EntryNotFound) as ei:
        run(adv, symbol="lane", file="rtl/top_adv.sv")          # a module name whose file is wrong
    assert "defined in rtl/lane.sv, not in rtl/top_adv.sv" in str(ei.value) or "instantiated" in str(ei.value)
    _, g = run(adv, symbol="top_adv.gen_lane[0].u_lane", file="rtl/lane.sv", depth=0)        # leaf module's file
    assert g.entry.endswith("gen_lane[0].u_lane")
    _, g = run(adv, symbol="top_adv.gen_lane[0].u_lane", file="rtl/top_adv.sv", depth=0)     # top module's file
    with pytest.raises(EntryNotFound) as ei:
        run(adv, symbol="top_adv.gen_lane[0].u_lane", file="rtl/fp.sv", depth=0)             # unrelated module's file
    assert "defines no module on the path" in str(ei.value)
    with pytest.raises(EntryNotFound):
        run(adv, symbol="bump", file="rtl/top_adv.sv")                                         # defined in adv_pkg.sv
    _, g = run(adv, symbol="bump", file="rtl/adv_pkg.sv", depth=0)
    assert g.entry == "sv:rtl/adv_pkg.sv::adv_pkg.bump"


# ---------------------------------------------------------------- H2 cache identity
def test_cache_identity_follows_environment_engine_and_nested_lists(adv, monkeypatch):
    monkeypatch.setenv("HX_SV_CFG", "cfg_a")
    fe_a, g_a = run(adv, filelist="env.f")
    assert fe_a.stats["cached"] == 0 and len([n for n in g_a.nodes.values() if n.kind == "instance"]) == 3   # one lane, no gen_multi
    fe_a2, g_a2 = run(adv, filelist="env.f")
    assert fe_a2.stats["cached"] == 1 and shape(g_a2) == shape(g_a)
    monkeypatch.setenv("HX_SV_CFG", "cfg_b")                      # only the environment changes
    fe_b, g_b = run(adv, filelist="env.f")
    assert fe_b.stats["cached"] == 0 and len([n for n in g_b.nodes.values() if n.kind == "instance"]) == 5
    assert "sv:rtl/lane.sv::top_adv.gen_multi.u_lane_star" in g_b.nodes
    # nested lists: root.f -> -F lists/parent.f -> -f sub/child.f (child resolved under lists/, its entries under root)
    fe_n, g_n = run(adv, filelist="root.f")
    assert fe_n.stats["cached"] == 0 and shape(g_n) == shape(g_b)
    child = adv / "lists" / "sub" / "child.f"
    child.write_text(child.read_text() + "\n// touched\n")
    fe_n2, _ = run(adv, filelist="root.f")
    assert fe_n2.stats["cached"] == 0                            # the nested list's content is part of the identity
    fe_n3, _ = run(adv, filelist="root.f")
    assert fe_n3.stats["cached"] == 1
    with pytest.raises(FrontendError):                           # a missing engine fails even with a warm cache
        run(adv, filelist="root.f", verilator="/nonexistent/verilator")
