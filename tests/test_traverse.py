"""Traversal semantics on an in-memory fake frontend (no libclang needed)."""
from hx.frontends.base import Frontend, FunctionRecord, DeclRecord, TypeRecord, CallSite
from hx.model import Node, Loc, TypeDef, Field, GlobalVar
from hx.traverse import TraverseOptions, extract_graph


class FakeFE(Frontend):
    lang = "fake"

    def __init__(self, calls, defined=None, system=(), types=None, node_types=None, node_globals=None):
        self.calls = calls                      # name -> [callee names]
        self.defined = set(defined if defined is not None else calls)
        self.system = set(system)
        self.types = types or {}                # tname -> (TypeDef, nested)
        self.node_types = node_types or {}      # fname -> [tnames]
        self.node_globals = node_globals or {}  # fname -> [global names]

    def _id(self, k):
        return f"fake:{k}.c::{k}"

    def locate_entry(self, file, symbol):
        return symbol

    def function(self, key):
        if key not in self.defined:
            return None
        n = Node(id=self._id(key), kind="function", name=key, qualname=key, lang="fake",
                 loc=Loc(f"{key}.c", 1), signature=f"void {key}()")
        cs = [CallSite(callee_key=c, name=c, loc=Loc(f"{key}.c", 2 + i), kind="call") for i, c in enumerate(self.calls.get(key, []))]
        cs += [CallSite(callee_key=None, name="(*fp)", loc=Loc(f"{key}.c", 99), kind="fnptr")] if key == "withfp" else []
        return FunctionRecord(node=n, callsites=cs, type_keys=self.node_types.get(key, []), global_keys=self.node_globals.get(key, []))

    def declaration(self, key):
        if key == "ghost":
            return None
        return DeclRecord(id=self._id(key), name=key, loc=Loc(f"{key}.h", 1), has_definition=key in self.defined,
                          system=key in self.system, relpath=f"{key}.c")

    def type(self, key):
        if key not in self.types:
            return None
        td, nested = self.types[key]
        return TypeRecord(typedef=TypeDef(**td), nested_keys=nested, alias_keys=[])

    def global_var(self, key):
        return GlobalVar(id=f"fake:g.c::{key}", name=key, type="int", lang="fake")

    def callers(self, key):
        return [(f, CallSite(callee_key=key, name=key, loc=Loc(f"{f}.c", 5), kind="call"))
                for f, cs in self.calls.items() if key in cs]

    def stable_id(self, key):
        return self._id(key)


def names(g):
    return {n.name: n.depth for n in g.nodes.values()}


def test_depth_limit_and_beyond_depth_reason():
    fe = FakeFE({"a": ["b"], "b": ["c"], "c": ["d"], "d": []})
    g = extract_graph(fe, "a.c", "a", TraverseOptions(depth=2), "/r")
    assert names(g) == {"a": 0, "b": 1, "c": 2}
    assert [u.reason for u in g.unresolved] == ["beyond depth limit"]
    assert g.unresolved[0].id == "fake:d.c::d"
    assert len(g.edges) == 3  # edges recorded even for the unexpanded target


def test_cycles_terminate_and_min_depth_wins():
    fe = FakeFE({"a": ["b", "c"], "b": ["a", "c"], "c": ["b"]})
    g = extract_graph(fe, "a.c", "a", TraverseOptions(depth=None), "/r")
    assert names(g) == {"a": 0, "b": 1, "c": 1}


def test_unresolved_kinds():
    fe = FakeFE({"a": ["nodef", "sysfn", "ghost", "withfp"], "withfp": []}, defined=["a", "withfp", "sysfn"], system=["sysfn"])
    g = extract_graph(fe, "a.c", "a", TraverseOptions(depth=3), "/r")
    reasons = {u.name: u.reason for u in g.unresolved}
    assert reasons == {"nodef": "no definition in TU set", "sysfn": "system header excluded",
                       "ghost": "unknown symbol", "(*fp)": "indirect call through function pointer"}
    fp_edges = [e for e in g.edges if e.kind == "fnptr"]
    assert len(fp_edges) == 1 and fp_edges[0].dst is None
    assert "withfp" in names(g)
    g2 = extract_graph(fe, "a.c", "a", TraverseOptions(depth=3, include_system=True), "/r")
    assert "sysfn" in names(g2)


def test_exclude_glob():
    fe = FakeFE({"a": ["b", "c"], "b": [], "c": []})
    g = extract_graph(fe, "a.c", "a", TraverseOptions(depth=3, exclude=["b*"]), "/r")
    assert set(names(g)) == {"a", "c"}
    assert g.unresolved[0].reason == "excluded by filter"


def test_max_nodes_truncates():
    fe = FakeFE({"a": ["b", "c", "d"], "b": [], "c": [], "d": []})
    g = extract_graph(fe, "a.c", "a", TraverseOptions(depth=3, max_nodes=2), "/r")
    assert len(g.nodes) == 2 and g.meta["truncated"] is True
    assert any(u.reason == "truncated by --max-nodes" for u in g.unresolved)


def test_truncation_records_every_dropped_target_from_a_node_in_the_graph():
    """Review finding H6: the unresolved `from` must be in the graph and no queued target may vanish."""
    fe = FakeFE({"a": ["b", "c", "d"], "b": ["e"], "c": [], "d": [], "e": []})
    g = extract_graph(fe, "a.c", "a", TraverseOptions(depth=3, max_nodes=2), "/r")
    assert set(names(g)) == {"a", "b"}
    trunc = {(u.name, u.src) for u in g.unresolved if u.reason == "truncated by --max-nodes"}
    assert trunc == {("c", "fake:a.c::a"), ("d", "fake:a.c::a"), ("e", "fake:b.c::b")}
    assert all(u.src in g.nodes for u in g.unresolved) and all(e.src in g.nodes for e in g.edges)
    assert {u.id for u in g.unresolved} == {"fake:c.c::c", "fake:d.c::d", "fake:e.c::e"}
    # callers side: a caller that does not fit is recorded against the callee, never as an edge from a missing node
    fe = FakeFE({"top": ["leaf"], "other": ["leaf"], "leaf": []})
    g = extract_graph(fe, "leaf.c", "leaf", TraverseOptions(depth=2, include_callers=True, max_nodes=2), "/r")
    assert len(g.nodes) == 2 and g.meta["truncated"] is True
    assert all(e.src in g.nodes for e in g.edges) and all(u.src in g.nodes for u in g.unresolved)
    assert any(u.reason == "caller truncated by --max-nodes" and u.src == "fake:leaf.c::leaf" for u in g.unresolved)


def test_callers_collect_globals_too():
    fe = FakeFE({"top": ["leaf"], "leaf": []}, node_globals={"top": ["g_top"], "leaf": ["g_leaf"]})
    g = extract_graph(fe, "leaf.c", "leaf", TraverseOptions(depth=1), "/r")
    assert set(g.globals) == {"fake:g.c::g_leaf"}
    g = extract_graph(fe, "leaf.c", "leaf", TraverseOptions(depth=1, include_callers=True), "/r")
    assert set(g.globals) == {"fake:g.c::g_leaf", "fake:g.c::g_top"}


def test_type_expansion_is_independent_of_visit_order():
    """A type first met deep (little budget left) and later used directly must still be expanded fully."""
    T = lambda i: dict(id=f"fake:t.h::struct {i}", kind="struct", name=i, lang="fake", fields=[Field(name="x", type="int")])
    types = {"t0": (T("t0"), ["t1"]), "t1": (T("t1"), ["t2"]), "t2": (T("t2"), ["t3"]), "t3": (T("t3"), ["t4"]), "t4": (T("t4"), [])}
    deep_first = FakeFE({"a": ["b"], "b": []}, types=types, node_types={"a": ["t0"], "b": ["t2"]})
    direct_first = FakeFE({"a": ["b"], "b": []}, types=types, node_types={"a": ["t2"], "b": ["t0"]})
    g1 = extract_graph(deep_first, "a.c", "a", TraverseOptions(type_depth=2), "/r")
    g2 = extract_graph(direct_first, "a.c", "a", TraverseOptions(type_depth=2), "/r")
    assert set(g1.types) == set(g2.types) == {f"fake:t.h::struct t{i}" for i in range(5)}   # t2 direct → t3 → t4
    g3 = extract_graph(FakeFE({"a": []}, types=types, node_types={"a": ["t0"]}), "a.c", "a", TraverseOptions(type_depth=2), "/r")
    assert set(g3.types) == {f"fake:t.h::struct t{i}" for i in range(3)}


def test_callers_negative_depth():
    fe = FakeFE({"top": ["mid"], "mid": ["leaf"], "leaf": [], "other": ["leaf"]})
    g = extract_graph(fe, "leaf.c", "leaf", TraverseOptions(depth=1, include_callers=True), "/r")
    assert names(g) == {"leaf": 0, "mid": -1, "other": -1}
    g = extract_graph(fe, "leaf.c", "leaf", TraverseOptions(depth=2, include_callers=True), "/r")
    assert names(g)["top"] == -2
    assert all(e.dst in {"fake:leaf.c::leaf", "fake:mid.c::mid"} for e in g.edges)


def test_type_depth_levels():
    T = lambda i: dict(id=f"fake:t.h::struct {i}", kind="struct", name=i, lang="fake", fields=[Field(name="x", type="int")])
    types = {"t0": (T("t0"), ["t1"]), "t1": (T("t1"), ["t2"]), "t2": (T("t2"), ["t3"]), "t3": (T("t3"), [])}
    fe = FakeFE({"a": []}, types=types, node_types={"a": ["t0"]})
    g = extract_graph(fe, "a.c", "a", TraverseOptions(type_depth=1), "/r")
    assert set(g.types) == {"fake:t.h::struct t0", "fake:t.h::struct t1"}
    assert g.types["fake:t.h::struct t0"].used_by == ["fake:a.c::a"]
    g = extract_graph(fe, "a.c", "a", TraverseOptions(type_depth=3), "/r")
    assert len(g.types) == 4


def test_graph_json_roundtrip():
    from hx.model import Graph
    fe = FakeFE({"a": ["b"], "b": []})
    g = extract_graph(fe, "a.c", "a", TraverseOptions(), "/r")
    d = g.to_dict()
    assert list(d)[:3] == ["schema", "generated", "root"]
    assert d["edges"][0]["from"] == "fake:a.c::a" and d["edges"][0]["to"] == "fake:b.c::b"
    g2 = Graph.from_dict(d)
    assert g2.edges[0].src == "fake:a.c::a" and g2.nodes["fake:a.c::a"].loc.file == "a.c"
    assert g2.to_dict() == d


def test_recursion_at_depth_limit_is_not_reported_as_beyond_depth():
    fe = FakeFE({"a": ["b"], "b": ["b", "a", "c"], "c": []})
    g = extract_graph(fe, "a.c", "a", TraverseOptions(depth=1), "/r")
    assert names(g) == {"a": 0, "b": 1}
    assert {u.name for u in g.unresolved} == {"c"}
    self_edges = [e for e in g.edges if e.src == e.dst]
    assert len(self_edges) == 1 and self_edges[0].src == "fake:b.c::b"
    assert "fake:a.c::a" in g.nodes["fake:b.c::b"].calls
