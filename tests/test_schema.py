"""The published IR schema (hx/schema/hx-4.schema.json) validates real graphs, and the loader enforces the major."""
import json
import os

import pytest

from hx.model import Graph, SchemaError

jsonschema = pytest.importorskip("jsonschema")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hx", "schema", "hx-4.schema.json")


def _validator():
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_c_graph_validates(extract):
    v = _validator()
    for kw in ({"depth": 3}, {"depth": 2, "include_callers": True, "include_system": True}, {"depth": 1, "max_nodes": 2}):
        d = extract(**kw).to_dict()
        assert d["meta"]["evidence_limits"] == ["entry-view-only"]
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


def test_loader_enforces_schema_major(tmp_path):
    from hx import graphio
    d = {"schema": "hx/4", "root": "/r", "lang": "c", "entry": "c:a.c::f", "nodes": {}, "types": {}, "globals": {}, "edges": [], "unresolved": []}
    assert Graph.from_dict(d).entry == "c:a.c::f"
    d2 = dict(d, schema="hx/4.3")           # minor additions are fine
    assert Graph.from_dict(d2).schema == "hx/4.3"
    with pytest.raises(SchemaError):
        Graph.from_dict(dict(d, schema="hx/5"))
    with pytest.raises(SchemaError):
        Graph.from_dict({k: v for k, v in d.items() if k != "schema"})
    with pytest.raises(SchemaError):
        Graph.from_dict(dict(d, schema="other/1"))
    for old in ("hx/1", "hx/2", "hx/3"):
        with pytest.raises(SchemaError):      # the dataclass boundary takes only the current major …
            Graph.from_dict(dict(d, schema=old))
        up, rep = graphio.upgrade(dict(d, schema=old))   # … the shared loader walks older majors up in memory first
        assert up["schema"] == "hx/4" and rep is not None and rep.from_schema == old and not rep.pending
        p = tmp_path / "old.json"
        p.write_text(json.dumps(dict(d, schema=old)))
        assert Graph.load(str(p)).schema == "hx/4"
    p = tmp_path / "new.json"
    p.write_text(json.dumps(dict(d, schema="hx/5")))
    with pytest.raises(SchemaError):
        Graph.load(str(p))


def test_chain_stamps_each_step():
    """`migrate_1_to_2` alone yields a literal hx/2 document (not the current major), so the chain cannot skip a step."""
    from hx import graphio
    d = {"schema": "hx/1", "root": "/r", "lang": "c", "entry": "c:a.c::f", "nodes": {}, "types": {}, "globals": {}, "edges": [], "unresolved": []}
    mid, rep = graphio.migrate_1_to_2(dict(d))
    assert mid["schema"] == "hx/2" and rep.from_schema == "hx/1"
    final, rep2 = graphio.migrate_2_to_3(mid)
    assert final["schema"] == "hx/3" and rep2.from_schema == "hx/2"
    assert list(graphio.MIGRATIONS) == ["1", "2", "3"]


def test_spice_graph_validates(tmp_path):
    import shutil
    from hx.api import extract
    fix = os.path.join(os.path.dirname(__file__), "fixtures", "spice", "ota")
    dst = tmp_path / "sp"
    shutil.copytree(fix, dst, ignore=shutil.ignore_patterns(".hx"))
    g = extract("ota.sp:.", root=str(dst), depth=None, dialect="ngspice").to_dict()
    errors = sorted(_validator().iter_errors(g), key=lambda e: list(e.path))
    assert errors == [], [f"{list(e.path)}: {e.message}" for e in errors[:5]]
    assert g["circuit"]["root"]["kind"] == "deck" and any(n["kind"] == "device" for n in g["nodes"].values())
    g2 = extract("ota.sp:xa", root=str(dst), depth=0, dialect="ngspice").to_dict()
    assert sorted(_validator().iter_errors(g2), key=lambda e: list(e.path)) == []
