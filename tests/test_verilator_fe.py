"""SystemVerilog frontend on tests/fixtures/sv via verilator --xml-only."""
import os
import shutil

import pytest

from hx.frontends.verilator_fe import VerilatorFrontend, parse_const
from hx.traverse import TraverseOptions, extract_graph

pytestmark = pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
FIX = os.path.join(os.path.dirname(__file__), "fixtures", "sv")


@pytest.fixture
def svproj(tmp_path):
    dst = tmp_path / "sv"
    shutil.copytree(FIX, dst)
    return dst


def run(root, symbol="top", file="rtl/top.sv", **opts):
    fe = VerilatorFrontend(str(root), filelist=str(root / "files.f"), top="top", use_cache=opts.pop("use_cache", True))
    fe.build_index()
    return fe, extract_graph(fe, file, symbol, TraverseOptions(**opts), str(root))


def test_parse_const():
    assert parse_const("32'sh10") == 16 and parse_const("2'h3") == 3 and parse_const("8'd255") == 255
    assert parse_const("4'b1010") == 10 and parse_const("7") == 7 and parse_const("4'bxxxx") == "4'bxxxx"


def test_hierarchy_nodes_and_edges(svproj):
    fe, g = run(svproj, depth=4)
    assert g.entry == "sv:rtl/top.sv::top" and g.lang == "sv"
    kinds = {n.qualname: (n.kind, n.depth) for n in g.nodes.values()}
    assert kinds["top"] == ("module", 0)
    assert kinds["top.u_core_a"] == ("instance", 1) and kinds["top.u_core_b"] == ("instance", 1)
    assert kinds["top.u_core_a.u_alu"] == ("instance", 2)
    assert kinds["core.saturate"] == ("function", 2) and kinds["core.pulse"] == ("task", 2) and kinds["dma_pkg.add_len"] == ("function", 2)
    inst_edges = [e for e in g.edges if e.kind == "instance"]
    assert len(inst_edges) == 4
    e = next(e for e in inst_edges if e.dst == "sv:rtl/core.sv::top.u_core_a")
    assert e.args[:3] == [".clk(clk)", ".rst_n(rst_n)", ".desc(desc)"] and e.loc.file == "rtl/top.sv" and e.loc.line == 20
    e = next(e for e in inst_edges if e.dst == "sv:rtl/alu.sv::top.u_core_a.u_alu")
    assert ".b(desc.cfg.len[W-1:0])" in e.args and ".lut('{default: '0})" in e.args
    calls = {(e.src.split("::")[1], e.dst.split("::")[1]): e.args for e in g.edges if e.kind == "call"}
    assert calls[("top.u_core_a", "dma_pkg.add_len")] == ["desc.cfg.len", "8'd1"]
    assert calls[("top.u_core_a", "core.pulse")] == ["pl"]
    assert g.unresolved == []


def test_ports_params_and_specializations(svproj):
    fe, g = run(svproj, depth=2)
    top = g.nodes[g.entry]
    assert top.signature.startswith("module top (clk, rst_n, src_addr")
    dirs = {p.name: (p.dir, p.dir_source) for p in top.params}
    assert dirs["clk"] == ("in", "explicit") and dirs["result_a"] == ("out", "explicit") and dirs["sda"] == ("inout", "explicit")
    cfg = next(p for p in top.params if p.name == "cfg")
    assert cfg.type == "dma_pkg::cfg_t" and cfg.type_ref == "sv:rtl/pkg.sv::struct dma_pkg::cfg_t"
    a = g.nodes["sv:rtl/core.sv::top.u_core_a"]
    b = g.nodes["sv:rtl/core.sv::top.u_core_b"]
    assert a.attrs["parameters"] == {"W": 8, "DEPTH": 4} and b.attrs["parameters"] == {"W": 16, "DEPTH": 4}
    assert a.attrs["specialization"] is None and b.attrs["specialization"] == "core__W10"
    assert a.signature.startswith("core #(W=8, DEPTH=4) u_core_a (")
    assert {s["name"] for s in a.attrs["signals"]} == {"acc", "zero", "pl"}
    st = next(p for p in a.params if p.name == "state")
    assert st.dir == "out" and st.type_ref == "sv:rtl/pkg.sv::enum dma_pkg::state_t"   # enum recovered from declared name
    alu = g.nodes["sv:rtl/alu.sv::top.u_core_a.u_alu"] if "sv:rtl/alu.sv::top.u_core_a.u_alu" in g.nodes else None
    assert alu is not None
    lut = next(p for p in alu.params if p.name == "lut")
    assert lut.type == "logic [7:0] [0:3]" and lut.dir == "in"   # unpacked dim as elaborated
    assert a.loc.file == "rtl/core.sv" and a.loc.line == 3


def test_types_bits_and_enums(svproj):
    fe, g = run(svproj, depth=1)
    cfg = g.types["sv:rtl/pkg.sv::struct dma_pkg::cfg_t"]
    assert cfg.size == 16
    assert [(f.name, f.bit_offset, f.bit_width) for f in cfg.fields] == [("len", 8, 8), ("chan", 4, 4), ("irq_en", 3, 1), ("prio", 0, 3)]
    desc = g.types["sv:rtl/pkg.sv::struct dma_pkg::desc_t"]
    assert desc.size == 80 and [(f.name, f.bit_offset) for f in desc.fields] == [("src", 48), ("dst", 16), ("cfg", 0)]
    assert next(f for f in desc.fields if f.name == "cfg").type_ref == cfg.id
    st = g.types["sv:rtl/pkg.sv::enum dma_pkg::state_t"]
    assert [(e.name, e.value) for e in st.enumerators] == [("IDLE", 0), ("BUSY", 1), ("DONE", 2), ("ERR", 3)]
    assert st.size == 2 and st.underlying == "logic [1:0]"
    alias = fe.type("alias:dma_pkg::cfg_t").typedef      # typedef aliases are indexed; graph includes them only when referenced
    assert alias.kind == "typedef" and alias.underlying_ref == cfg.id and alias.id == "sv:rtl/pkg.sv::dma_pkg::cfg_t"
    assert g.entry in cfg.used_by


def test_entry_forms_and_errors(svproj):
    from hx.frontends.base import EntryNotFound
    fe, g = run(svproj, symbol="top.u_core_b.u_alu", depth=0)
    assert g.entry == "sv:rtl/alu.sv::top.u_core_b.u_alu" and len(g.nodes) == 1
    assert [u.reason for u in g.unresolved] == []
    fe, g = run(svproj, symbol="saturate", file="rtl/core.sv", depth=0)
    assert g.entry == "sv:rtl/core.sv::core.saturate"
    with pytest.raises(EntryNotFound) as ei:
        run(svproj, symbol="core")                      # instantiated twice: ambiguous
    assert set(ei.value.suggestions) == {"top.u_core_a", "top.u_core_b"}
    with pytest.raises(EntryNotFound):
        run(svproj, symbol="nope")


def test_callers_and_cache(svproj):
    fe, g = run(svproj, symbol="top.u_core_a.u_alu", depth=2, include_callers=True)
    depths = {n.qualname: n.depth for n in g.nodes.values()}
    assert depths == {"top.u_core_a.u_alu": 0, "top.u_core_a": -1, "top": -2}
    fe, g = run(svproj, symbol="add_len", file="rtl/pkg.sv", depth=1, include_callers=True)
    assert {n.qualname for n in g.nodes.values() if n.depth < 0} == {"top.u_core_a", "top.u_core_b"}
    assert fe.stats["cached"] == 1   # second build in the same tree hit the cache
    (svproj / "rtl" / "alu.sv").write_text((svproj / "rtl" / "alu.sv").read_text() + "\n// touched\n")
    import time
    os.utime(svproj / "rtl" / "alu.sv", (time.time() + 3, time.time() + 3))
    fe, g = run(svproj, depth=1)
    assert fe.stats["cached"] == 0
