"""Observed source provenance, Git boundaries, and cache-independent fingerprints."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import jsonschema
import pytest

from hx import provenance
from hx.api import extract
from hx.diff import diff_graphs


def deck(root):
    root.mkdir(parents=True, exist_ok=True)
    source = root / "deck.sp"
    source.write_text("Observed deck\n.include lib.inc\nx1 in 0 cell\n.end\n")
    (root / "lib.inc").write_text(".subckt cell a b\nr1 a b 1k\n.ends cell\n")
    return source


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def init(root):
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "hx-test@example.invalid")
    git(root, "config", "user.name", "hx tests")


def commit(root):
    git(root, "add", ".")
    git(root, "commit", "-qm", "test source")
    return git(root, "rev-parse", "HEAD")


def manifest(graph):
    return {item["path"]: item for item in graph.meta["provenance"]["inputs"]["files"]}


def test_native_cold_and_warm_runs_have_stable_fingerprints(tmp_path):
    source = deck(tmp_path / "source")
    first = extract("deck.sp:.", root=str(source.parent))
    second = extract("deck.sp:.", root=str(source.parent))
    a, b = first.meta["provenance"], second.meta["provenance"]
    assert a["run_id"] != b["run_id"] and a["started"] <= a["completed"]
    assert a["git"]["status"] == "no-repo"
    assert first.meta["index"]["parsed"] and second.meta["index"]["cached"]
    assert a["inputs"]["sha256"] == b["inputs"]["sha256"]
    assert a["options_sha256"] == b["options_sha256"] and a["graph_sha256"] == b["graph_sha256"]
    assert not diff_graphs(first.to_dict(), second.to_dict())["summary"]["any"]
    files = manifest(first)
    assert {"deck.sp", "lib.inc"} <= files.keys()
    assert all(files[p]["status"] == "ok" for p in ("deck.sp", "lib.inc"))
    assert files["lib.inc"]["sha256"] == hashlib.sha256((source.parent / "lib.inc").read_bytes()).hexdigest()
    assert not (source.parent / ".hx/graphs").exists()  # Python remains in-memory
    schema = json.loads((Path(__file__).parents[1] / "hx/schema/hx-3.schema.json").read_text())
    jsonschema.validate(first.to_dict(), schema)


def test_same_commit_different_dirty_edits_have_distinct_inputs(tmp_path):
    source = deck(tmp_path)
    init(tmp_path)
    revision = commit(tmp_path)
    clean = extract("deck.sp:.", root=str(tmp_path))
    assert clean.meta["provenance"]["git"]["commit"] == revision
    assert clean.meta["provenance"]["git"]["dirty"] is False
    assert clean.meta["provenance"]["git"]["changed_during_extract"] is False
    for value in ("2k", "3k"):
        (tmp_path / "lib.inc").write_text(f".subckt cell a b\nr1 a b {value}\n.ends cell\n")
        item = extract("deck.sp:.", root=str(tmp_path))
        state = item.meta["provenance"]["git"]
        assert state["commit"] == revision and state["dirty"] is True
        assert item.meta["provenance"]["inputs"]["sha256"] != clean.meta["provenance"]["inputs"]["sha256"]
        clean = item


def test_submodule_revision_is_independent_of_hx_root(tmp_path):
    library = tmp_path / "library"
    deck(library)
    init(library)
    revision = commit(library)
    outer = tmp_path / "outer"
    init(outer)
    (outer / ".github").mkdir()
    git(outer, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(library), "component")
    commit(outer)
    graph = extract("component/deck.sp:.", root=str(outer))
    state = graph.meta["provenance"]["git"]
    assert state["commit"] == revision and state["repo_root"] == str(outer / "component")
    assert graph.root == str(outer)


def test_worktree_and_unborn_head(tmp_path):
    root = tmp_path / "repo"
    deck(root)
    init(root)
    unborn = provenance.git_state(str(root / "deck.sp"))
    assert unborn["status"] == "unborn" and unborn["commit"] is None and unborn["dirty"]
    revision = commit(root)
    worktree = tmp_path / "worktree"
    git(root, "worktree", "add", "--detach", "-q", str(worktree), "HEAD")
    state = provenance.git_state(str(worktree / "deck.sp"))
    assert state["repo_root"] == str(worktree) and state["commit"] == revision


def test_missing_git_does_not_fail_native_extraction(tmp_path, monkeypatch):
    deck(tmp_path)
    monkeypatch.setenv("PATH", "")
    graph = extract("deck.sp:.", root=str(tmp_path))
    assert graph.meta["provenance"]["git"]["status"] == "unavailable"
    assert graph.meta["provenance"]["git"]["diagnostic"]


def test_git_environment_does_not_redirect_source_repo(tmp_path, monkeypatch):
    one, two = tmp_path / "one", tmp_path / "two"
    for root in (one, two):
        deck(root)
        init(root)
        commit(root)
    monkeypatch.setenv("GIT_DIR", str(two / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(two))
    assert provenance.git_state(str(one / "deck.sp"))["repo_root"] == str(one)


def test_missing_and_changed_inputs_are_explicit(tmp_path):
    source = deck(tmp_path)
    missing = tmp_path / "missing.inc"
    old_stamp = source.stat().st_mtime_ns
    os.utime(source, ns=(old_stamp + 1000, old_stamp + 1000))
    fe = SimpleNamespace(provenance_inputs=lambda: {str(source): old_stamp, str(missing): None})
    observed = provenance.observed_inputs(fe, str(tmp_path), str(source), {})
    files = {f["path"]: f for f in observed["files"]}
    assert files["deck.sp"]["status"] == "changed"
    assert files["missing.inc"] == {"path": "missing.inc", "sha256": None, "status": "missing"}
    assert observed["changed_during_extract"]
    missing.write_text("created after discovery")
    observed = provenance.observed_inputs(fe, str(tmp_path), str(source), {})
    assert next(f for f in observed["files"] if f["path"] == "missing.inc")["status"] == "changed"


def test_unreadable_input_and_discovery_failure_are_diagnostics(tmp_path, monkeypatch):
    source = deck(tmp_path)
    unreadable = tmp_path / "unreadable.inc"
    unreadable.write_text("source")
    fe = SimpleNamespace(provenance_inputs=lambda: {str(unreadable): unreadable.stat().st_mtime_ns})
    import builtins
    real_open = builtins.open

    def fail(path, *args, **kwargs):
        if os.fspath(path) == str(unreadable):
            raise PermissionError("injected unreadable input")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail)
    observed = provenance.observed_inputs(fe, str(tmp_path), str(source), {})
    assert next(f for f in observed["files"] if f["path"] == "unreadable.inc")["status"] == "unreadable"

    def broken():
        raise OSError("injected input discovery failure")

    fe.provenance_inputs = broken
    assert provenance.observed_inputs(fe, str(tmp_path), str(source), {})["diagnostics"]


def test_external_inputs_stay_absolute_and_config_is_observed(tmp_path):
    root = tmp_path / "source"
    deck(root)
    external = tmp_path / "outside.inc"
    external.write_text(".subckt cell a b\nr1 a b 4k\n.ends cell\n")
    (root / "deck.sp").write_text("external source\n.include ../outside.inc\nx1 in 0 cell\n.end\n")
    (root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    graph = extract("deck.sp:.", root=str(root))
    assert str(external) in manifest(graph) and "pyproject.toml" in manifest(graph)


def test_c_headers_and_compile_database_observed_on_warm_cache(cproj):
    first = extract("src/main.c:app_run", root=str(cproj), jobs=1)
    second = extract("src/main.c:app_run", root=str(cproj), jobs=1)
    files = manifest(second)
    assert "build/compile_commands.json" in files
    assert any(p.startswith("include/") for p in files)
    assert first.meta["provenance"]["inputs"]["sha256"] == second.meta["provenance"]["inputs"]["sha256"]
    assert first.meta["provenance"]["graph_sha256"] == second.meta["provenance"]["graph_sha256"]


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_sv_design_and_argument_files_observed_on_warm_cache(tmp_path):
    root = tmp_path / "sv"
    shutil.copytree(Path(__file__).parent / "fixtures/sv", root, ignore=shutil.ignore_patterns(".hx", "obj_dir"))
    first = extract("rtl/top.sv:top", root=str(root), filelist=str(root / "files.f"))
    second = extract("rtl/top.sv:top", root=str(root), filelist=str(root / "files.f"))
    files = manifest(second)
    assert {"files.f", "rtl/top.sv", "rtl/alu.sv"} <= files.keys()
    assert first.meta["provenance"]["inputs"]["sha256"] == second.meta["provenance"]["inputs"]["sha256"]


def test_lsp_observed_documents_and_configs(tmp_path):
    from hx.frontends.lsp_fe import LspFrontend
    root = tmp_path / "python"
    root.mkdir()
    (root / "main.py").write_text("def f():\n    return 1\n")
    (root / "pyrightconfig.json").write_text("{}")
    fe = LspFrontend(str(root), server="python", cmd=["unused"])
    fe.client = SimpleNamespace(notify=lambda *args: None, shutdown=lambda: None)
    try:
        fe._open(str(root / "main.py"))
        observed = provenance.observed_inputs(fe, str(root), str(root / "main.py"), {})
        assert {"main.py", "pyrightconfig.json"} <= {f["path"] for f in observed["files"]}
    finally:
        fe.close()


def test_source_and_git_changes_during_extraction_are_flagged(tmp_path, monkeypatch):
    import hx.api as api
    deck(tmp_path)
    init(tmp_path)
    original_revision = commit(tmp_path)
    real_make = api.make_frontend

    def make_then_edit(*args, **kwargs):
        result = real_make(*args, **kwargs)
        (tmp_path / "lib.inc").write_text(".subckt cell a b\nr1 a b 9k\n.ends cell\n")
        git(tmp_path, "add", "lib.inc")
        git(tmp_path, "commit", "-qm", "edit during extraction")
        return result

    monkeypatch.setattr(api, "make_frontend", make_then_edit)
    graph = api.extract("deck.sp:.", root=str(tmp_path))
    record = graph.meta["provenance"]
    assert record["git"]["commit"] == original_revision
    assert record["git"]["changed_during_extract"]
    assert record["git"]["at_completion"]["commit"] != original_revision
    assert record["inputs"]["changed_during_extract"] and manifest(graph)["lib.inc"]["status"] == "changed"
