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
    shutil.copytree(os.path.join(FIX, "c"), dst, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
    write_compile_commands(dst)
    fe = ClangFrontend(str(dst), str(dst / "build"), jobs=1)
    fe.build_index()
    return fe, str(dst), "src/main.c", "app_run", "c:src/dma.c::dma_start"


def _sv(tmp_path):
    if not shutil.which("verilator"):
        pytest.skip("verilator missing")
    dst = tmp_path / "sv"
    shutil.copytree(os.path.join(FIX, "sv"), dst, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
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
    shutil.copytree(os.path.join(FIX, "python"), dst, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
    fe = LspFrontend(str(dst), server="python", timeout=120)
    fe.build_index()
    return fe, str(dst), "hxfix/main.py", "app_run", "py:hxfix/dma.py::dma_start"


def _spice(tmp_path):
    from hx.frontends.spice_fe import SpiceFrontend
    dst = tmp_path / "spice"
    shutil.copytree(os.path.join(FIX, "spice", "ota"), dst, ignore=shutil.ignore_patterns(".hx", "__pycache__"))
    fe = SpiceFrontend(str(dst), deck="ota.sp", dialect="ngspice")
    fe.build_index()
    return fe, str(dst), "ota.sp", ".", "sp:ota.sp::xa"


def _spice_nested(tmp_path):
    """Guarded instances under guarded instances, references with alternatives, a ghost reference."""
    from hx.frontends.spice_fe import SpiceFrontend
    dst = tmp_path / "spice_nested"
    shutil.copytree(os.path.join(FIX, "spice", "conditional"), dst, ignore=shutil.ignore_patterns(".hx", "__pycache__"))
    fe = SpiceFrontend(str(dst), deck="nested_guard.sp", dialect="ngspice")
    fe.build_index()
    return fe, str(dst), "nested_guard.sp", ".", "sp:nested_guard.sp::v1"


def _check_circuit(g, fe=None):
    """`terminals` and `ports` are keyed by graph nodes only (a definition's `instances` and a model's `used_by` may
    name unresolved ghost ids); every terminal's net exists with a binding or a terminal; canonical nets follow each
    node's own ancestor chain; every occurrence's guard extends its parent's; references point at nodes or ghosts,
    with unique targets and a diagnostic when two targets overlap; every declaration reference and every
    ambiguous or missing instance ghost is serialised — under truncation and depth 0 too."""
    from hx.netlist.names import guard_compatible
    c = g.circuit
    assert c is not None and c["root"]["id"] == g.entry and c["root"]["deck_role"] in ("deck", "library")
    ghosts = {u.id for u in g.unresolved if u.id}
    for nid, terms in c["terminals"].items():
        assert nid in g.nodes, nid
        for t in terms:
            assert t["net"] in c["nets"] and t["canonical"] in c["nets"], (nid, t)
            assert any(x[0] == nid for x in c["nets"][t["net"]]["terminals"]) or c["nets"][t["net"]]["kind"] in ("ground", "global"), (nid, t)
    for nid, ports in c["ports"].items():
        assert nid in g.nodes and g.nodes[nid].kind == "instance", nid
        for b in ports:
            assert b["inner"] in c["nets"] and b["outer"] in c["nets"] and b["net"] in c["nets"], b
            if c["nets"][b["inner"]]["kind"] not in ("global", "ground"):          # a port named like a global IS the global
                assert any(x["via"] == nid for x in c["nets"][b["inner"]]["bindings"]), b
            if fe is not None:
                tag, occ = fe._occ[fe._by_id[nid]]
                assert b["net"] == fe._elabs[tag].canonical(b["outer"], occ), (nid, b)
    idents = {k: {d["identity"] for rec in c[k].values() for d in rec["declarations"]} for k in ("definitions", "models")}
    for n in g.nodes.values():
        for ref in n.attrs.get("definition_refs", []):
            assert ref["key"] in idents["definitions"], (n.id, ref)
        for ref in n.attrs.get("model_refs", []):
            assert ref["key"] in idents["models"], (n.id, ref)
        if n.kind == "device":
            assert n.id in c["terminals"] or n.attrs.get("family") == "?", n.id
            for ctl in n.attrs.get("controls", []):
                assert ctl["targets"] and len(set(ctl["targets"])) == len(ctl["targets"]), ctl
                assert all(t in g.nodes or t in ghosts for t in ctl["targets"]), ctl
                if fe is not None:
                    real = [fe._occ[fe._by_id[t]][1] for t in ctl["targets"] if t in g.nodes]
                    if any(guard_compatible(a.guard, b.guard) for i, a in enumerate(real) for b in real[i + 1:]):
                        assert any(d["code"] == "ambiguous-reference" and d["node"] == n.id for d in c["diagnostics"]), (n.id, ctl)
        for p in [x for x in g.nodes.values() if n.qualname.startswith(x.qualname.split("#")[0] + ".") and x.kind in ("instance", "module")]:
            pg, ng = p.attrs.get("guard_id"), n.attrs.get("guard_id")
            if pg:
                assert ng, (p.id, n.id)      # a child under a guarded instance is guarded too
    for rec in list(c["definitions"].values()) + list(c["models"].values()) + list(c["params"].values()):
        assert rec["status"] in ("found", "alternatives", "ambiguous", "binned", "shadowed", "missing")
        for d in rec["declarations"]:
            assert d["identity"].endswith("#" + d["guard_id"]) if d["guard_id"] else "#" not in d["identity"], d
    for e in g.edges:
        if e.kind == "ref":
            assert e.dst in g.nodes or e.dst in ghosts, e
    listed = {i for rec in c["definitions"].values() for i in rec.get("instances", [])}
    for u in g.unresolved:
        if u.id and (u.reason.startswith("ambiguous:") or u.reason.startswith("no .subckt definition")):
            assert u.id in listed, u


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
    if g.lang == "sp":
        _check_circuit(g, fe)
    if opts.max_nodes is not None:
        assert len(g.nodes) <= opts.max_nodes
        capped = any("max-nodes" in u.reason for u in g.unresolved)
        assert g.meta["truncated"] == capped, (g.meta["truncated"], capped)      # the flag and the unresolved evidence agree
        if capped:
            assert len(g.nodes) >= opts.max_nodes
    for n in g.nodes.values():
        if opts.depth is not None:
            assert abs(n.depth) <= opts.depth


@pytest.mark.parametrize("make", [_c, _sv, _rust, _python, _spice, _spice_nested], ids=["c", "sv", "rust", "python", "spice", "spice-nested"])
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
