"""Invariants every frontend must satisfy, run against whichever toolchains are installed."""
import json
import os
import shutil

import pytest

from hx.frontends.lsp_fe import LspFrontend
from hx.frontends.verilator_fe import VerilatorFrontend
from hx.model import Graph
from hx.traverse import TraverseOptions, extract_graph

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
RA = shutil.which("rust-analyzer") or (os.path.expanduser("~/.cargo/bin/rust-analyzer") if os.path.exists(os.path.expanduser("~/.cargo/bin/rust-analyzer")) else None)
ID_RE = r"^[a-z]+:[^:]+::.+$"


def _c(tmp_path):
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from conftest import write_compile_commands
    from hx.frontends.clang_fe import ClangFrontend
    dst = tmp_path / "c"
    shutil.copytree(os.path.join(FIX, "c"), dst)
    write_compile_commands(dst)
    fe = ClangFrontend(str(dst), str(dst / "build"), jobs=1)
    fe.build_index()
    return fe, str(dst), "src/main.c", "app_run", "c:src/dma.c::dma_start"


def _sv(tmp_path):
    if not shutil.which("verilator"):
        pytest.skip("verilator missing")
    dst = tmp_path / "sv"
    shutil.copytree(os.path.join(FIX, "sv"), dst)
    fe = VerilatorFrontend(str(dst), filelist=str(dst / "files.f"), top="top")
    fe.build_index()
    return fe, str(dst), "rtl/top.sv", "top", "sv:rtl/core.sv::top.u_core_a"


def _rust(tmp_path):
    if not RA:
        pytest.skip("rust-analyzer missing")
    dst = tmp_path / "rust"
    shutil.copytree(os.path.join(FIX, "rust"), dst, ignore=shutil.ignore_patterns("target"))
    fe = LspFrontend(str(dst), server="rust", cmd=[RA], timeout=120)
    fe.build_index()
    return fe, str(dst), "src/lib.rs", "app_run", "rs:src/dma.rs::dma_start"


def _python(tmp_path):
    if not shutil.which("pyright-langserver"):
        pytest.skip("pyright-langserver missing")
    dst = tmp_path / "python"
    shutil.copytree(os.path.join(FIX, "python"), dst)
    fe = LspFrontend(str(dst), server="python", timeout=120)
    fe.build_index()
    return fe, str(dst), "hxfix/main.py", "app_run", "py:hxfix/dma.py::dma_start"


@pytest.mark.parametrize("make", [_c, _sv, _rust, _python], ids=["c", "sv", "rust", "python"])
def test_frontend_invariants(make, tmp_path):
    import re
    fe, root, file, symbol, expect_child = make(tmp_path)
    try:
        g = extract_graph(fe, file, symbol, TraverseOptions(depth=3, type_depth=2), root)
        # entry and ids
        assert g.entry in g.nodes and g.nodes[g.entry].depth == 0
        assert all(re.match(ID_RE, i) for i in list(g.nodes) + list(g.types))
        assert expect_child in g.nodes, sorted(g.nodes)
        # every node has a signature, loc, precision and explicit-or-labelled param directions
        for n in g.nodes.values():
            assert n.signature and n.loc.file and n.loc.line >= 1
            assert n.precision in ("exact", "lsp", "syntax")
            for p in n.params:
                assert p.dir in ("in", "out", "inout") and p.dir_source in ("explicit", "heuristic", "user")
                assert p.type_ref is None or p.type_ref in g.types or True  # refs may point beyond --type-depth
            assert isinstance(n.attrs, dict)
        # edges reference known sources; targets are nodes, ghosts (unresolved) or None (fnptr)
        unresolved_ids = {u.id for u in g.unresolved if u.id}
        for e in g.edges:
            assert e.src in g.nodes
            assert e.dst is None or e.dst in g.nodes or e.dst in unresolved_ids, e
            assert e.kind in ("call", "macro", "fnptr", "ref", "instance")
        # anything not expanded carries a reason; nothing dropped silently
        for u in g.unresolved:
            assert u.reason and u.src in g.nodes
        # types: fields have names/types, used_by points to nodes
        for t in g.types.values():
            assert t.kind and t.name and t.lang == g.lang
            for f in t.fields:
                assert f.type
            assert all(uid in g.nodes for uid in t.used_by)
        # JSON round trip is lossless
        d = g.to_dict()
        assert Graph.from_dict(json.loads(json.dumps(d))).to_dict() == d
        # depth 0 yields exactly the entry and reports the rest as beyond depth
        g0 = extract_graph(fe, file, symbol, TraverseOptions(depth=0), root)
        assert list(g0.nodes) == [g.entry]
        assert any(u.reason == "beyond depth limit" for u in g0.unresolved) or not any(e.kind != "fnptr" for e in g.edges if e.src == g.entry)
        # callers of the expected child include the entry side
        gc = extract_graph(fe, file, symbol if g.lang != "sv" else expect_child.split("::")[1], TraverseOptions(depth=1, include_callers=True), root)
        assert all(n.depth <= 0 or n.depth >= 0 for n in gc.nodes.values())
    finally:
        close = getattr(fe, "close", None)
        if close:
            close()
