"""Rust configuration freshness, including candidates absent before indexing."""
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from hx import project, provenance
from hx.config_inputs import rust_config_candidates, snapshot_inputs
from hx.frontends.lsp_fe import LspFrontend


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "src/lib.rs").write_text("pub fn entry() {}\n")
    (root / "Cargo.toml").write_text('[package]\nname="config_probe"\nversion="0.1.0"\n')
    monkeypatch.setenv("CARGO_HOME", str(tmp_path / "cargo-home"))
    return root


@pytest.mark.parametrize("relative", ["rust-toolchain", "rust-toolchain.toml", ".cargo/config", ".cargo/config.toml"])
def test_config_creation_edit_deletion_changes_watch_and_provenance(workspace, relative):
    root = workspace
    path = root / relative
    fe = SimpleNamespace(provenance_inputs=lambda: snapshot_inputs(rust_config_candidates(str(root))))
    def observe():
        sig = project.source_signature(str(root), paths=["src"])
        inputs = provenance.observed_inputs(fe, str(root), str(root / "src/lib.rs"), {})
        return sig, inputs
    initial, first = observe()
    assert initial[str(path)] == project.MISSING
    path.parent.mkdir(exist_ok=True)
    path.write_text("first configuration\n")
    created, second = observe()
    path.write_text("changed configuration\n")
    os.utime(path, ns=(created[str(path)] + 1000000, created[str(path)] + 1000000))
    edited, third = observe()
    path.unlink()
    deleted, fourth = observe()
    assert initial != created != edited != deleted
    assert deleted[str(path)] == project.MISSING
    assert first["sha256"] != second["sha256"] != third["sha256"] != fourth["sha256"]
    assert first["sha256"] == fourth["sha256"]


def test_ancestor_cargo_home_and_legacy_candidates(workspace, monkeypatch):
    root = workspace
    monkeypatch.setenv("CARGO_HOME", "custom-cargo")
    paths = rust_config_candidates(str(root))
    assert paths == sorted(set(paths))
    assert str(root.parent / ".cargo/config.toml") in paths
    assert str(root.parent / "rust-toolchain") in paths
    assert str(root / "custom-cargo/config") in paths
    assert str(root / "custom-cargo/config.toml") in paths
    assert all("credentials" not in p for p in paths)
    # Member configs are not effective just because a member source is read.
    member = root / "member/.cargo/config.toml"
    member.parent.mkdir(parents=True)
    member.write_text("[build]\n")
    assert str(member) not in paths
    ancestor = root.parent / ".cargo/config.toml"
    before = project.source_signature(str(root), paths=["src"])
    ancestor.parent.mkdir(exist_ok=True)
    ancestor.write_text("[build]\n")
    assert project.source_signature(str(root), paths=["src"]) != before


@pytest.mark.parametrize("mutation", ["create", "edit", "delete"])
def test_indexing_records_configuration_changes_from_before_server_start(workspace, monkeypatch, mutation):
    from hx.frontends import lsp_fe
    path = workspace / "rust-toolchain.toml"
    if mutation != "create":
        path.write_text("before indexing\n")
    fe = LspFrontend(str(workspace))

    class Client:
        def __init__(self, *args):
            assert str(path) in fe.provenance_inputs()
            if mutation == "delete":
                path.unlink()
            else:
                path.write_text("changed during server startup\n")
                stamp = fe.provenance_inputs()[str(path)] or path.stat().st_mtime_ns
                os.utime(path, ns=(stamp + 1000000, stamp + 1000000))

        def initialize(self): pass
        def wait_ready(self, timeout): pass
        def shutdown(self): pass

    monkeypatch.setattr(lsp_fe, "LspClient", Client)
    try:
        fe.build_index()
        inputs = provenance.observed_inputs(fe, str(workspace), str(workspace / "src/lib.rs"), {})
        assert inputs["changed_during_extract"]
        assert next(f for f in inputs["files"] if f["path"] == path.name)["status"] == "changed"
    finally:
        fe.close()


@pytest.mark.parametrize("mutation", ["create", "edit", "delete"])
def test_watch_refreshes_rust_config_before_any_successful_extraction(workspace, monkeypatch, mutation):
    root = str(workspace)
    project.track(root, "src/lib.rs:entry")
    (workspace / "Cargo.toml").unlink()  # tracking bootstraps discovery without a manifest/graph
    cfg = project.load_config(root)
    cfg["watch"]["paths"] = ["src"]
    project.save_config(root, cfg)
    path = workspace / ".cargo/config.toml"
    path.parent.mkdir()
    if mutation != "create":
        path.write_text("before\n")
    updates = []
    monkeypatch.setattr(project, "update", lambda root: updates.append(root) or [])
    iterations = 0
    def stop():
        nonlocal iterations
        iterations += 1
        if iterations == 1:
            if mutation == "delete":
                path.unlink()
            else:
                before = path.stat().st_mtime_ns if path.exists() else None
                path.write_text("after\n")
                if before is not None:
                    os.utime(path, ns=(before + 1000000, before + 1000000))
        return iterations > 6
    assert project.watch(root, interval=0.001, debounce=0, run_first=False,
                         max_updates=1, stop=stop) == 1
    assert updates == [root]


def test_saved_provenance_and_older_rust_graphs_supply_dependencies(workspace):
    graphs = workspace / ".hx/graphs"
    graphs.mkdir(parents=True)
    external = workspace.parent / "outside.rs"
    (graphs / "old.json").write_text(json.dumps({"lang": "rs", "root": str(workspace)}))
    (graphs / "unknown.json").write_text(json.dumps({"meta": {"provenance": {"inputs": None}}}))
    (graphs / "new.json").write_text(json.dumps({"root": str(workspace), "meta": {
        "provenance": {"inputs": {"files": [{"path": str(external), "status": "missing"},
                                            {"path": "src/lib.rs", "status": "ok"}]}}}}))
    dependencies = project.dependency_files(str(workspace))
    assert {str(external), str(workspace / "src/lib.rs"), str(workspace / "rust-toolchain.toml")} <= dependencies.keys()
    assert project.source_signature(str(workspace), extra=dependencies)[str(external)] == project.MISSING


def test_live_rust_extraction_captures_config_candidates(tmp_path, monkeypatch):
    from conftest import require_tool
    from hx.api import extract
    ra = require_tool("rust-analyzer", os.path.expanduser("~/.cargo/bin/rust-analyzer"))
    monkeypatch.setenv("PATH", str(Path(ra).parent) + os.pathsep + os.environ["PATH"])
    root = tmp_path / "rust"
    shutil.copytree(Path(__file__).parent / "fixtures/rust", root,
                    ignore=shutil.ignore_patterns("target", ".hx"))
    config = root / ".cargo/config.toml"
    config.parent.mkdir()
    config.write_text("[build]\njobs = 1\n")
    graph = extract("src/lib.rs:app_run", root=str(root), depth=1, lsp_timeout=120)
    files = {f["path"]: f for f in graph.meta["provenance"]["inputs"]["files"]}
    assert files[".cargo/config.toml"]["status"] == "ok"
    assert files[".cargo/config.toml"]["sha256"]
    assert files["rust-toolchain.toml"]["status"] == "missing"
