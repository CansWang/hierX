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
    assert split_top("a, f(b, c), d<x, y>") == ["a", "f(b, c)", "d<x, y>"]


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
    shutil.copytree(os.path.join(FIX, "python"), dst)
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
