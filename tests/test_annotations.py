import json

from hx import annotations as A


def test_merge_patch_semantics():
    base = {"a": {"x": 1, "y": 2}, "b": [1, 2], "c": "s"}
    out = A.merge_patch(base, {"a": {"y": None, "z": 3}, "b": [9], "d": {"n": 1}})
    assert out == {"a": {"x": 1, "z": 3}, "b": [9], "c": "s", "d": {"n": 1}}
    assert base["a"] == {"x": 1, "y": 2}  # input not mutated
    assert A.merge_patch({"k": {"deep": 1}}, {"k": "flat"}) == {"k": "flat"}


def test_normalize_tolerates_garbage():
    doc = A.normalize({"nodes": {"id": {"note": "x"}, "bad": 5}, "types": "nope", "view": {"hidden": ["a", 3], "pinned_positions": {"a": {"x": 1}, "b": 2}}})
    assert doc["schema"] == A.SCHEMA
    assert doc["nodes"] == {"id": {"note": "x"}} and doc["types"] == {}
    assert doc["view"] == {"hidden": ["a"], "pinned_positions": {"a": {"x": 1}}}
    assert A.normalize(None) == A.empty()


def test_patch_file_roundtrip_and_recursive_prune(tmp_path):
    p = str(tmp_path / "annotations.json")
    doc = A.patch_file(p, {"nodes": {"n1": {"note": "hi", "tags": ["a"], "params": {"ch": {"dir": "out"}}, "collapsed": True}}})
    assert json.load(open(p))["nodes"]["n1"]["params"]["ch"]["dir"] == "out"
    doc = A.patch_file(p, {"nodes": {"n1": {"tags": None, "params": {"ch": {"dir": None}}, "collapsed": None}}})
    assert doc["nodes"]["n1"] == {"note": "hi"}          # empty params/ch pruned, false-y collapsed pruned
    doc = A.patch_file(p, {"nodes": {"n1": {"note": None}}})
    assert doc["nodes"] == {}                             # whole node entry gone
    assert A.load(p)["schema"] == A.SCHEMA
    assert A.load(str(tmp_path / "missing.json")) == A.empty()


def test_effective_dir():
    node = {"id": "n1", "params": [{"name": "ch", "dir": "inout", "dir_source": "heuristic"}]}
    assert A.effective_dir(node, A.empty(), "ch") == ("inout", "heuristic")
    ann = {"nodes": {"n1": {"params": {"ch": {"dir": "out"}}}}}
    assert A.effective_dir(node, ann, "ch") == ("out", "user")
