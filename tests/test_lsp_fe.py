"""Generic LSP frontend against rust-analyzer (Rust fixture crate) and pyright (Python fixture package)."""
import os
import shutil

import pytest

from hx.frontends.lsp_fe import LspFrontend, parse_signature, split_top
from hx.traverse import TraverseOptions, extract_graph

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
RA = shutil.which("rust-analyzer") or (os.path.expanduser("~/.cargo/bin/rust-analyzer") if os.path.exists(os.path.expanduser("~/.cargo/bin/rust-analyzer")) else None)
PYRIGHT = shutil.which("pyright-langserver")


def test_parse_signature_rust():
    params, ret = parse_signature("pub fn dma_start(ch: &mut DmaChan, buf: &[u8]) -> Result<usize, DmaError>", "rs")
    assert [(p["name"], p["type"], p["dir"]) for p in params] == [("ch", "&mut DmaChan", "inout"), ("buf", "&[u8]", "in")]
    assert ret == "Result<usize, DmaError>"
    params, ret = parse_signature("pub fn set_callback(&mut self, cb: Callback)", "rs")
    assert params[0] == {"name": "self", "type": "&mut Self", "dir": "inout"} and ret is None
    params, _ = parse_signature("fn f(mut a: Vec<(i32, u8)>, b: &'a str)", "rs")
    assert [(p["name"], p["type"]) for p in params] == [("a", "Vec<(i32, u8)>"), ("b", "&'a str")]


def test_parse_signature_python():
    params, ret = parse_signature("(function) def app_run( data: bytes, n: int = 3, *args: str, **kw: int ) -> int", "py")
    assert [(p["name"], p["type"]) for p in params] == [("data", "bytes"), ("n", "int"), ("args", "tuple[str, ...]"), ("kw", "dict[str, int]")]
    assert params[1]["default"] == "3" and ret == "int"
    assert split_top("a, f(b, c), d<x, y>", lang="rs") == ["a", "f(b, c)", "d<x, y>"]      # generics only in Rust
    assert split_top('a, "x, y", f(b, c)') == ["a", '"x, y"', "f(b, c)"]                  # H1: literals are opaque
    # H3: the apragma hover with `sep: str = ","` — nine parameters, no phantom `"` parameter
    hover = ('(function) def save_ds_data(\n    ds: xr.Dataset,\n    path: str | Path,\n    fmt: str = "csv",\n'
             '    sel: dict[str, Any] | None = None,\n    isel: dict[str, int] | None = None,\n'
             '    physical_vars: list[str] | None = None,\n    coord_order: tuple[str, ...] = ("x", "y"),\n'
             '    float_format: str = "%.6e",\n    sep: str = ","\n) -> Path')
    params, ret = parse_signature(hover, "py")
    assert [p["name"] for p in params] == ["ds", "path", "fmt", "sel", "isel", "physical_vars", "coord_order", "float_format", "sep"]
    assert params[-1]["default"] == '","' and params[6]["default"] == '("x", "y")' and ret == "Path"
    assert params[3]["type"] == "dict[str, Any] | None" and not any(p["name"] == '"' for p in params)
    params, ret = parse_signature('def run(cmd: str = " 2>&1 ", n: int = 1) -> int', "py")
    assert [(p["name"], p["default"]) for p in params] == [("cmd", '" 2>&1 "'), ("n", "1")] and ret == "int"


@pytest.fixture
def rust_fe(tmp_path):
    if not RA:
        pytest.skip("rust-analyzer not installed")
    dst = tmp_path / "rust"
    shutil.copytree(os.path.join(FIX, "rust"), dst, ignore=shutil.ignore_patterns("target"))
    fe = LspFrontend(str(dst), server="rust", cmd=[RA], timeout=120)
    fe.build_index()
    yield fe, dst
    fe.close()


@pytest.fixture
def py_fe(tmp_path):
    if not PYRIGHT:
        pytest.skip("pyright-langserver not installed")
    dst = tmp_path / "python"
    shutil.copytree(os.path.join(FIX, "python"), dst, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
    fe = LspFrontend(str(dst), server="python", timeout=120)
    fe.build_index()
    yield fe, dst
    fe.close()


def test_rust_hierarchy(rust_fe):
    fe, root = rust_fe
    g = extract_graph(fe, "src/lib.rs", "app_run", TraverseOptions(depth=3, type_depth=2), str(root))
    assert g.entry == "rs:src/lib.rs::app_run" and g.lang == "rs"
    depths = {n.id: n.depth for n in g.nodes.values()}
    assert depths["rs:src/dma.rs::dma_start"] == 1 and depths["rs:src/dma.rs::DmaChan::set_callback"] == 1
    assert depths["rs:src/dma.rs::prog_desc"] == 2 and depths["rs:src/hal.rs::write32"] == 2
    assert "rs:src/dma.rs::DmaError" not in g.nodes                      # tuple-struct constructor is not a function
    assert all(n.precision == "lsp" for n in g.nodes.values())
    start = g.nodes["rs:src/dma.rs::dma_start"]
    assert [(p.name, p.type, p.dir, p.dir_source) for p in start.params] == [("ch", "&mut DmaChan", "inout", "heuristic"), ("buf", "&[u8]", "in", "heuristic")]
    assert start.params[0].type_ref == "rs:src/dma.rs::struct DmaChan" and start.returns.type == "Result<usize, DmaError>"
    cb = g.nodes["rs:src/dma.rs::DmaChan::set_callback"]
    assert cb.params[0].type == "&mut Self" and cb.params[1].type_ref is None   # fn-pointer alias must not resolve to Desc
    assert cb.attrs["module"] == "hxfix::dma::DmaChan"
    e = next(e for e in g.edges if e.dst == "rs:src/dma.rs::dma_start")
    assert e.args == ["&mut ch", "&data[..n.min(data.len())]"] and e.loc.file == "src/lib.rs" and e.loc.line == 11
    chan = g.types["rs:src/dma.rs::struct DmaChan"]
    assert [(f.name, f.type) for f in chan.fields] == [("base", "usize"), ("desc", "Desc"), ("cb", "Option<Callback>"), ("busy", "bool")]
    assert next(f for f in chan.fields if f.name == "desc").type_ref == "rs:src/dma.rs::struct Desc"
    assert chan.size is None
    reasons = {u.name: u.reason for u in g.unresolved}
    assert reasons["min"] == "outside project root (library)" and reasons["DmaError"].startswith("not a function")
    assert "write_volatile" in reasons


def test_rust_callers(rust_fe):
    fe, root = rust_fe
    g = extract_graph(fe, "src/hal.rs", "write32", TraverseOptions(depth=1, include_callers=True), str(root))
    assert {n.qualname: n.depth for n in g.nodes.values()} == {"write32": 0, "prog_desc": -1, "dma_start": -1}


def test_python_hierarchy(py_fe):
    fe, root = py_fe
    g = extract_graph(fe, "hxfix/main.py", "app_run", TraverseOptions(depth=3, type_depth=2), str(root))
    assert g.entry == "py:hxfix/main.py::app_run" and g.lang == "py"
    ids = set(g.nodes)
    assert {"py:hxfix/dma.py::dma_start", "py:hxfix/dma.py::dma_poll", "py:hxfix/dma.py::_prog_desc", "py:hxfix/hal.py::write32", "py:hxfix/hal.py::read32"} <= ids
    assert "py:hxfix/dma.py::DmaChan" not in ids                          # class instantiation is not a function node
    start = g.nodes["py:hxfix/dma.py::dma_start"]
    assert [(p.name, p.type, p.dir, p.dir_source) for p in start.params] == [("ch", "DmaChan", "in", "explicit"), ("buf", "bytes", "in", "explicit")]
    assert start.params[0].type_ref == "py:hxfix/dma.py::class DmaChan" and start.returns.type == "int"
    e = next(e for e in g.edges if e.dst == "py:hxfix/dma.py::dma_start")
    assert e.args == ["ch", "data[:n]"] and e.loc.line == 11
    chan = g.types["py:hxfix/dma.py::class DmaChan"]
    assert [(f.name, f.type) for f in chan.fields] == [("base", "int"), ("desc", "Desc"), ("cb", "Optional[Callback]"), ("busy", "bool")]
    assert next(f for f in chan.fields if f.name == "desc").type_ref == "py:hxfix/dma.py::class Desc"
    desc = g.types["py:hxfix/dma.py::class Desc"]
    assert [(f.name, f.type) for f in desc.fields] == [("src", "int"), ("dst", "int"), ("length", "int"), ("flags", "int")]
    reasons = {u.name: u.reason for u in g.unresolved}
    assert reasons["len"] == "outside project root (library)" and reasons["DmaChan"].startswith("not a function")


def test_python_entry_errors(py_fe):
    from hx.frontends.base import EntryNotFound
    fe, root = py_fe
    with pytest.raises(EntryNotFound) as ei:
        extract_graph(fe, "hxfix/main.py", "app_rnu", TraverseOptions(), str(root))
    assert "app_run" in ei.value.suggestions


def test_python_indentation_change_is_a_body_change(py_fe):
    """Review finding H1: dedenting `return -1` out of its `if` makes the return unconditional; the hash must move."""
    fe, dst = py_fe
    g0 = extract_graph(fe, "hxfix/main.py", "app_run", TraverseOptions(depth=2), str(dst))
    nid = "py:hxfix/dma.py::dma_start"
    dma = dst / "hxfix" / "dma.py"
    src = dma.read_text()
    assert "    if not buf:\n        return -1\n" in src
    dma.write_text(src.replace("    if not buf:\n        return -1\n", "    if not buf:\n        pass\n    return -1\n"))
    fe2 = LspFrontend(str(dst), server="python", timeout=120)
    fe2.build_index()
    try:
        g1 = extract_graph(fe2, "hxfix/main.py", "app_run", TraverseOptions(depth=2), str(dst))
    finally:
        fe2.close()
    assert g1.nodes[nid].body_hash != g0.nodes[nid].body_hash
    dma.write_text(src.replace("    n = _prog_desc(ch, buf)\n", "    # program the descriptor first\n    n = _prog_desc(ch,   buf)\n"))
    fe3 = LspFrontend(str(dst), server="python", timeout=120)
    fe3.build_index()
    try:
        g2 = extract_graph(fe3, "hxfix/main.py", "app_run", TraverseOptions(depth=2), str(dst))
    finally:
        fe3.close()
    assert g2.nodes[nid].body_hash == g0.nodes[nid].body_hash


def test_python_nested_function_ids_include_the_enclosing_function(py_fe):
    """Review finding H2: `outer_a.helper` and `outer_b.helper` are distinct, carry no position hash, survive a line
    shift, and resolve as qualified entries."""
    from hx.frontends.base import EntryNotFound
    fe, root = py_fe
    g = extract_graph(fe, "hxfix/nested.py", "review", TraverseOptions(depth=3), str(root))
    ids = set(g.nodes)
    assert {"py:hxfix/nested.py::outer_a.helper", "py:hxfix/nested.py::outer_b.helper"} <= ids, ids
    assert not any("#" in i for i in ids)
    ga = extract_graph(fe, "hxfix/nested.py", "outer_a.helper", TraverseOptions(depth=0), str(root))
    assert ga.entry == "py:hxfix/nested.py::outer_a.helper"
    with pytest.raises(EntryNotFound):
        extract_graph(fe, "hxfix/nested.py", "not_a_scope.helper", TraverseOptions(depth=0), str(root))
    p = root / "hxfix" / "nested.py"
    p.write_text("\n\n\n" + p.read_text())                      # three blank lines: every position moves
    fe2 = LspFrontend(str(root), server="python", timeout=120)
    fe2.build_index()
    try:
        g2 = extract_graph(fe2, "hxfix/nested.py", "review", TraverseOptions(depth=3), str(root))
        assert set(g2.nodes) == ids
        for i in ("py:hxfix/nested.py::outer_a.helper", "py:hxfix/nested.py::outer_b.helper"):
            assert g2.nodes[i].body_hash == g.nodes[i].body_hash and g2.nodes[i].loc.line == g.nodes[i].loc.line + 3
    finally:
        fe2.close()


def _count_requests(fe):
    import collections
    counts = collections.Counter()
    orig = fe._req

    def counting(method, params, timeout=None):
        counts[method] += 1
        return orig(method, params, timeout)
    fe._req = counting
    return counts


def test_python_module_caller_is_a_module_node(py_fe):
    """Review finding H5: a module-level call makes a `module` node spanning the file whose hash covers the file."""
    from hx import ids
    fe, root = py_fe
    counts = _count_requests(fe)
    g = extract_graph(fe, "hxfix/dma.py", "dma_poll", TraverseOptions(depth=1, include_callers=True), str(root))
    mid = "py:hxfix/script.py::(module) script.py"
    m = g.nodes[mid]
    text = (root / "hxfix" / "script.py").read_text()
    assert m.kind == "module" and m.depth == -1 and m.loc.line == 1 and m.loc.end_line == len(text.splitlines())
    assert m.body_hash == ids.body_hash(text, "py") and m.signature == "module script.py" and m.params == [] and m.returns is None
    assert counts["callHierarchy/outgoingCalls"] <= len(g.nodes)       # one fetch per admitted caller, none for the module
    assert any(e.src == mid and e.dst == "py:hxfix/dma.py::dma_poll" for e in g.edges)
    p = root / "hxfix" / "script.py"
    p.write_text(text.replace("VDD = 3.3", "VDD = 3.2"))                 # an executable edit below line 1
    fe2 = LspFrontend(str(root), server="python", timeout=120)
    fe2.build_index()
    try:
        g2 = extract_graph(fe2, "hxfix/dma.py", "dma_poll", TraverseOptions(depth=1, include_callers=True), str(root))
        assert g2.nodes[mid].body_hash != m.body_hash and g2.nodes[mid].kind == "module"
    finally:
        fe2.close()


def test_overload_family_collapses(py_fe):
    """Pyright returns one call-hierarchy item per `@overload`; a verified stub family is ONE target with metadata."""
    fe, root = py_fe
    g = extract_graph(fe, "hxfix/ovl.py", "use_overloads", TraverseOptions(depth=1), str(root))
    ghosts = {u.id: u for u in g.unresolved}
    ga = [i for i in ghosts if i.endswith("builtins.pyi::getattr")]
    assert len(ga) == 1 and not any("builtins.pyi::getattr#" in i for i in ghosts)
    assert ghosts[ga[0]].family == {"size": 6, "evidence": "@overload", "scope": "<module>"}
    sj = [i for i in ghosts if i.endswith("builtins.pyi::str.join")]
    assert len(sj) == 1 and not any(i.endswith("builtins.pyi::join") for i in ghosts) and ghosts[sj[0]].family["scope"] == "str"
    assert not any("#" in u.id.split("::")[-1] for u in g.unresolved)


def test_overload_families_respect_scope(py_fe):
    fe, root = py_fe
    g = extract_graph(fe, "hxfix/ovl.py", "use_overloads", TraverseOptions(depth=1), str(root))
    ghosts = {u.id: u for u in g.unresolved}
    assert ghosts["py:fakelib/__init__.pyi::A.get"].family == {"size": 3, "evidence": "@overload", "scope": "A"}
    assert ghosts["py:fakelib/__init__.pyi::B.get"].family == {"size": 2, "evidence": "@overload", "scope": "B"}   # never merged with A.get
    assert ghosts["py:fakelib/__init__.pyi::fetch"].family == {"size": 3, "evidence": "@overload", "scope": "<module>"}
    a_edges = [e for e in g.edges if e.dst == "py:fakelib/__init__.pyi::A.get"]
    assert [e.args for e in a_edges] == [["1"], ['"x"'], ["2.0"]] and len({e.loc.line for e in a_edges}) == 3   # one target, three call sites
    assert len([e for e in g.edges if e.dst == "py:fakelib/__init__.pyi::B.get"]) == 1


def test_unknown_scope_does_not_collapse(py_fe, monkeypatch):
    fe, root = py_fe
    monkeypatch.setattr(LspFrontend, "_scope_label", lambda self, item: None)     # no container evidence at all
    g = extract_graph(fe, "hxfix/ovl.py", "use_overloads", TraverseOptions(depth=1), str(root))
    ga = sorted(i for i in {u.id for u in g.unresolved} if "builtins.pyi::getattr" in i)
    assert len(ga) == 6 and sum("#" in i for i in ga) == 5                        # six separate targets, no family
    assert all(u.family is None for u in g.unresolved)


def test_family_metadata_round_trip(py_fe, tmp_path):
    """extraction -> save -> load -> schema -> migration mapper: the `family` field survives every hop."""
    import copy
    import json
    import jsonschema
    from hx import graphio, project
    fe, root = py_fe
    g = extract_graph(fe, "hxfix/ovl.py", "use_overloads", TraverseOptions(depth=1), str(root))
    gp = tmp_path / "g.json"
    g.save(str(gp))
    loaded = project.load_graph(str(gp))
    fam = [u for u in loaded["unresolved"] if u["id"].endswith("builtins.pyi::getattr")]
    assert len(fam) == 1 and fam[0]["family"]["size"] == 6
    schema = json.load(open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "hx", "schema", "hx-3.schema.json")))
    jsonschema.Draft202012Validator(schema).validate(loaded)
    rec = fam[0]
    stub = rec["id"].rpartition("::")[0]
    hashes = ("1a1a1a1a", "2b2b2b2b", "3c3c3c3c", "4d4d4d4d", "5e5e5e5e")
    old = copy.deepcopy(loaded)
    old["schema"] = "hx/2"
    old["unresolved"] = [u for u in old["unresolved"] if u["id"] != rec["id"]] + [dict(rec, family=None)] + \
        [dict(rec, id=f"{stub}::getattr#{h}", family=None) for h in hashes]
    old_up, rep = graphio.upgrade(old)
    assert rep.from_schema == "hx/2"
    node_map, _, _ = project.map_node_ids(old_up, loaded, str(root))
    mapped, ambiguous, unmapped = project.map_ghost_ids(old_up, loaded, node_map)
    assert all(mapped[f"{stub}::getattr#{h}"] == rec["id"] for h in hashes) and mapped[rec["id"]] == rec["id"]
    assert not ambiguous and not unmapped
