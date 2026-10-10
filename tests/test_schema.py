"""The published IR schema (hx/schema/hx-1.schema.json) validates real graphs, and the loader enforces the major."""
import json
import os

import pytest

from hx.model import Graph, SchemaError

jsonschema = pytest.importorskip("jsonschema")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hx", "schema", "hx-1.schema.json")


def _validator():
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_c_graph_validates(extract):
    v = _validator()
    for kw in ({"depth": 3}, {"depth": 2, "include_callers": True, "include_system": True}, {"depth": 1, "max_nodes": 2}):
        d = extract(**kw).to_dict()
        errors = sorted(v.iter_errors(d), key=lambda e: list(e.path))
        assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:10])
        assert all(u["from"] in d["nodes"] for u in d["unresolved"])


def test_fake_graph_validates_and_roundtrips():
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from test_traverse import FakeFE
    from hx.traverse import TraverseOptions, extract_graph
    g = extract_graph(FakeFE({"a": ["b", "c"], "b": [], "c": []}), "a.c", "a", TraverseOptions(), "/r")
    d = json.loads(g.to_json())
    assert not list(_validator().iter_errors(d))
    assert Graph.from_dict(d).to_dict() == g.to_dict()


def test_loader_enforces_schema_major():
    d = {"schema": "hx/1", "root": "/r", "lang": "c", "entry": "c:a.c::f", "nodes": {}, "types": {}, "globals": {}, "edges": [], "unresolved": []}
    assert Graph.from_dict(d).entry == "c:a.c::f"
    d2 = dict(d, schema="hx/1.3")           # minor additions are fine
    assert Graph.from_dict(d2).schema == "hx/1.3"
    with pytest.raises(SchemaError):
        Graph.from_dict(dict(d, schema="hx/2"))
    with pytest.raises(SchemaError):
        Graph.from_dict({k: v for k, v in d.items() if k != "schema"})
    with pytest.raises(SchemaError):
        Graph.from_dict(dict(d, schema="other/1"))
