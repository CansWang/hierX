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


def _symbol_of(nid: str) -> tuple[str, str]:
    """(file, symbol) to re-enter at a node id: 'c:src/dma.c::dma_start' → ('src/dma.c', 'dma_start')."""
    head, sym = nid.split("::", 1)
    return head.split(":", 1)[1], sym


def _check_invariants(g, fe, opts):
    import re
    assert g.entry in g.nodes and g.nodes[g.entry].depth == 0
    assert all(re.match(ID_RE, i) for i in list(g.nodes) + list(g.types))
    for n in g.nodes.values():
        assert n.signature and n.loc.file and n.loc.line >= 1
        assert n.precision in ("exact", "lsp", "syntax")
        assert n.body_hash and n.body_hash.startswith("sha1:")
        for p in n.params:
            assert p.dir in ("in", "out", "inout") and p.dir_source in ("explicit", "heuristic", "user")
            assert p.type_ref is None or p.type_ref in g.types, (n.id, p)      # level-0 types are always expanded
        if n.returns and n.returns.type_ref:
            assert n.returns.type_ref in g.types
        assert isinstance(n.attrs, dict)
        for c in n.calls:
            assert c in g.nodes or any(u.id == c for u in g.unresolved), (n.id, c)
    ghost_ids = {u.id for u in g.unresolved if u.id}
    for e in g.edges:
        assert e.src in g.nodes, e                                              # never an edge from a missing node
        assert e.dst is None or e.dst in g.nodes or e.dst in ghost_ids, e
        assert e.kind in ("call", "macro", "fnptr", "ref", "instance")
    for u in g.unresolved:
        assert u.reason and u.src in g.nodes, u                                # nothing dropped silently
    for t in g.types.values():
        assert t.kind and t.name and t.lang == g.lang
        for f in t.fields:
            assert f.type
            if f.type_ref and f.type_ref not in g.types:
                assert opts.type_depth < 99, (t.id, f)                          # may dangle only when the budget ran out
        assert all(uid in g.nodes for uid in t.used_by)
    d = g.to_dict()
    assert Graph.from_dict(json.loads(json.dumps(d))).to_dict() == d
    if opts.max_nodes is not None:
        assert len(g.nodes) <= opts.max_nodes
        assert g.meta["truncated"] == (len(g.nodes) >= opts.max_nodes and any("max-nodes" in u.reason for u in g.unresolved)) or not g.meta["truncated"]
    for n in g.nodes.values():
        if opts.depth is not None:
            assert abs(n.depth) <= opts.depth


@pytest.mark.parametrize("make", [_c, _sv, _rust, _python], ids=["c", "sv", "rust", "python"])
def test_frontend_invariants(make, tmp_path):
    """Every frontend must satisfy the same invariants — on the happy path AND under truncation, caller expansion,
    exclusion filters and different type budgets (the review found the happy path alone proved little)."""
    fe, root, file, symbol, expect_child = make(tmp_path)
    try:
        base = TraverseOptions(depth=3, type_depth=2)
        g = extract_graph(fe, file, symbol, base, root)
        _check_invariants(g, fe, base)
        assert expect_child in g.nodes, sorted(g.nodes)
        child_file, child_sym = _symbol_of(expect_child)
        variants = [
            TraverseOptions(depth=0),
            TraverseOptions(depth=3, type_depth=0),
            TraverseOptions(depth=3, type_depth=99),
            TraverseOptions(depth=3, max_nodes=2),
            TraverseOptions(depth=3, max_nodes=1, include_callers=True),
            TraverseOptions(depth=3, exclude=[child_file]),
        ]
        for opts in variants:
            gv = extract_graph(fe, file, symbol, opts, root)
            _check_invariants(gv, fe, opts)
        # depth 0: exactly the entry; its direct callees are reported as beyond depth
        g0 = extract_graph(fe, file, symbol, TraverseOptions(depth=0), root)
        assert list(g0.nodes) == [g.entry]
        direct = [e for e in g.edges if e.src == g.entry and e.kind != "fnptr"]
        if direct:
            assert any(u.reason == "beyond depth limit" for u in g0.unresolved), g0.unresolved
        # excluding the child's file turns the child into an unresolved record with that reason
        gx = extract_graph(fe, file, symbol, TraverseOptions(depth=3, exclude=[child_file]), root)
        assert expect_child not in gx.nodes
        assert any(u.id == expect_child and u.reason == "excluded by filter" for u in gx.unresolved), gx.unresolved
        # a bigger type budget never yields fewer types, and the budget-0 run keeps only level-0 types
        t0 = set(extract_graph(fe, file, symbol, TraverseOptions(depth=3, type_depth=0), root).types)
        t99 = set(extract_graph(fe, file, symbol, TraverseOptions(depth=3, type_depth=99), root).types)
        assert t0 <= set(g.types) <= t99
        # callers: entering at the child with --include-callers brings the original entry back at a negative depth
        gc = extract_graph(fe, child_file, child_sym, TraverseOptions(depth=1, include_callers=True), root)
        _check_invariants(gc, fe, TraverseOptions(depth=1, include_callers=True))
        assert gc.entry == expect_child
        assert g.entry in gc.nodes and gc.nodes[g.entry].depth == -1, {n.id: n.depth for n in gc.nodes.values()}
        assert any(e.src == g.entry and e.dst == expect_child for e in gc.edges)
    finally:
        close = getattr(fe, "close", None)
        if close:
            close()
