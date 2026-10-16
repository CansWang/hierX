"""Shared current/history contract, including interrupted and competing writers."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from hx import project
from hx.model import Graph

ENTRY = "src/a.c:f"


def graph(root, entry=ENTRY, sequence=0, **kwargs):
    file, symbol = entry.rsplit(":", 1)
    return Graph(root=str(root), lang="c", entry=f"c:{file}::{symbol}",
                 meta={"entry_arg": entry, "sequence": sequence}, **kwargs)


def current(root, entry=ENTRY):
    return Path(project.graph_path(str(root), entry))


def test_default_and_per_entry_current_share_history(tmp_path):
    root = str(tmp_path)
    first = project.save_extraction(root, ENTRY, graph(root), refresh_default=True)
    default = tmp_path / ".hx/graph.json"
    assert first.previous is None and project.list_history(root, ENTRY) == []
    assert current(root).read_bytes() == default.read_bytes()
    old = current(root).read_bytes()
    second = project.save_extraction(root, ENTRY, graph(root, sequence=1))
    assert Path(second.previous).read_bytes() == old
    assert current(root).read_bytes() == default.read_bytes()
    assert second.old_graph["meta"]["sequence"] == 0
    assert default.as_posix() in second.mirrors
    other = "src/b.c:g"
    saved = project.save_extraction(root, other, graph(root, other), refresh_default=True)
    assert saved.previous is None
    assert json.loads(default.read_bytes())["meta"]["entry_arg"] == other
    assert project.load_graph(str(current(root)))["meta"]["sequence"] == 1
    assert project.list_history(root, other) == []
    project.save_extraction(root, ENTRY, graph(root, sequence=2))
    assert json.loads(default.read_bytes())["meta"]["entry_arg"] == other


def test_legacy_default_is_preserved_before_entry_switch(tmp_path):
    default = tmp_path / ".hx/graph.json"
    graph(tmp_path).save(str(default))
    original = default.read_bytes()
    other = "src/b.c:g"
    project.save_extraction(str(tmp_path), other, graph(tmp_path, other), refresh_default=True)
    assert current(tmp_path).read_bytes() == original
    assert project.list_history(str(tmp_path), ENTRY) == []
    assert project.list_history(str(tmp_path), other) == []


def test_legacy_same_entry_becomes_previous_version(tmp_path):
    default = tmp_path / ".hx/graph.json"
    graph(tmp_path).save(str(default))
    old = default.read_bytes()
    saved = project.save_extraction(str(tmp_path), ENTRY, graph(tmp_path, sequence=1), refresh_default=True)
    assert Path(saved.previous).read_bytes() == old
    assert "-unknown-" in saved.previous


def test_snapshots_keep_old_provenance_and_reuse_identical_bytes(tmp_path):
    old = graph(tmp_path)
    old.meta["provenance"] = {"run_id": "1" * 32, "git": {"commit": "a" * 40, "dirty": True}}
    project.save_extraction(str(tmp_path), ENTRY, old)
    payload = current(tmp_path).read_bytes()
    baseline = project.snapshot(str(tmp_path), ENTRY)
    assert "-aaaaaaaaaaaa-dirty-" in baseline
    assert project.snapshot(str(tmp_path), ENTRY) == baseline
    new = graph(tmp_path, sequence=1)
    new.meta["provenance"] = {"run_id": "2" * 32, "git": {"commit": "b" * 40, "dirty": False}}
    saved = project.save_extraction(str(tmp_path), ENTRY, new)
    assert saved.previous == baseline and Path(baseline).read_bytes() == payload
    assert len(project.list_history(str(tmp_path), ENTRY)) == 1


def test_same_timestamp_and_run_id_never_overwrite_history(tmp_path):
    for sequence in range(3):
        item = graph(tmp_path, sequence=sequence, generated="2026-10-14T00:00:00+00:00")
        item.meta["provenance"] = {"run_id": "1" * 32}
        project.save_extraction(str(tmp_path), ENTRY, item)
    snapshots = project.list_history(str(tmp_path), ENTRY)
    assert len(snapshots) == 2
    assert {project.load_graph(s["path"])["meta"]["sequence"] for s in snapshots} == {0, 1}


def test_standalone_output_and_history_protection(tmp_path):
    output = tmp_path / "review.json"
    saved = project.save_extraction(str(tmp_path), ENTRY, graph(tmp_path), output=str(output), archive=False)
    assert output.exists() and saved.previous is None
    assert not (tmp_path / ".hx").exists()
    history = tmp_path / ".hx/history/case/old.json"
    with pytest.raises(ValueError, match="immutable"):
        project.save_extraction(str(tmp_path), ENTRY, graph(tmp_path), output=str(history), archive=False)
    assert not history.exists()
    # A viewer can archive/re-extract a standalone output without creating a managed current file.
    old = output.read_bytes()
    saved = project.save_extraction(str(tmp_path), ENTRY, graph(tmp_path, sequence=1), output=str(output))
    assert Path(saved.previous).read_bytes() == old and not current(tmp_path).exists()


@pytest.mark.parametrize("keep", [0, 2])
def test_retention_only_removes_old_versions(tmp_path, keep):
    for sequence in range(5):
        project.save_extraction(str(tmp_path), ENTRY, graph(tmp_path, sequence=sequence), keep_history=keep)
    snapshots = project.list_history(str(tmp_path), ENTRY)
    assert len(snapshots) == keep
    if keep:
        assert [project.load_graph(s["path"])["meta"]["sequence"] for s in snapshots] == [2, 3]
    assert project.load_graph(str(current(tmp_path)))["meta"]["sequence"] == 4
    with pytest.raises(ValueError, match="zero or greater"):
        project.save_extraction(str(tmp_path), ENTRY, graph(tmp_path), keep_history=-1)


def test_configured_baseline_retention(tmp_path):
    project.save_config(str(tmp_path), {"entries": [], "watch": {"history": 0}})
    project.save_extraction(str(tmp_path), ENTRY, graph(tmp_path))
    assert project.snapshot(str(tmp_path), ENTRY) is None
    assert project.list_history(str(tmp_path), ENTRY) == []


@pytest.mark.parametrize("payload", [b"invalid graph", b'{"schema":"hx/3"}'])
def test_corrupt_managed_current_is_not_replaced(tmp_path, payload):
    path = current(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        project.save_extraction(str(tmp_path), ENTRY, graph(tmp_path))
    assert path.read_bytes() == payload


def test_failed_mirror_is_reported_and_next_save_repairs_it(tmp_path, monkeypatch):
    root = str(tmp_path)
    default = tmp_path / ".hx/graph.json"
    project.save_extraction(root, ENTRY, graph(root), refresh_default=True)
    real_write = project.atomic_write

    def fail_mirror(path, data):
        if Path(path) == default:
            raise OSError("injected mirror failure")
        return real_write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(project, "atomic_write", fail_mirror)
        with pytest.raises(project.GraphSaveError, match="current committed") as error:
            project.save_extraction(root, ENTRY, graph(root, sequence=1))
        assert error.value.committed
    assert project.load_graph(str(current(root)))["meta"]["sequence"] == 1
    assert json.loads(default.read_bytes())["meta"]["sequence"] == 0
    project.save_extraction(root, ENTRY, graph(root, sequence=2))
    assert current(root).read_bytes() == default.read_bytes()
    assert [project.load_graph(h["path"])["meta"]["sequence"] for h in project.list_history(root, ENTRY)] == [0, 1]


def test_failed_current_preserves_previous_bytes_and_does_not_prune(tmp_path, monkeypatch):
    root = str(tmp_path)
    project.save_extraction(root, ENTRY, graph(root))
    before = current(root).read_bytes()
    real_write = project.atomic_write

    def fail_current(path, data):
        if Path(path) == current(root):
            raise OSError("injected current failure")
        return real_write(path, data)

    monkeypatch.setattr(project, "atomic_write", fail_current)
    with pytest.raises(project.GraphSaveError, match="current not committed"):
        project.save_extraction(root, ENTRY, graph(root, sequence=1), keep_history=1)
    assert current(root).read_bytes() == before
    assert Path(project.list_history(root, ENTRY)[0]["path"]).read_bytes() == before


@pytest.mark.parametrize("existing_default", [False, True])
def test_interrupted_default_selection_repairs_on_any_managed_save(tmp_path, monkeypatch, existing_default):
    root = str(tmp_path)
    default = tmp_path / ".hx/graph.json"
    if existing_default:
        project.save_extraction(root, ENTRY, graph(root), refresh_default=True)
    real_write = project.atomic_write

    def fail_mirror(path, data):
        if Path(path) == default:
            raise OSError("injected default selection failure")
        return real_write(path, data)

    other = "src/b.c:g"
    with monkeypatch.context() as patch:
        patch.setattr(project, "atomic_write", fail_mirror)
        with pytest.raises(project.GraphSaveError) as error:
            project.save_extraction(root, other, graph(root, other), refresh_default=True)
        assert error.value.committed
    project.save_extraction(root, ENTRY, graph(root, sequence=1))
    assert default.read_bytes() == current(root, other).read_bytes()
    assert not (tmp_path / ".hx/default-pending.json").exists()


def test_competing_threads_keep_every_previous_run(tmp_path):
    def save(sequence):
        return project.save_extraction(str(tmp_path), ENTRY, graph(tmp_path, sequence=sequence), refresh_default=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(save, range(12)))
    values = {project.load_graph(h["path"])["meta"]["sequence"] for h in project.list_history(str(tmp_path), ENTRY)}
    values.add(project.load_graph(str(current(tmp_path)))["meta"]["sequence"])
    assert values == set(range(12))
    assert current(tmp_path).read_bytes() == (tmp_path / ".hx/graph.json").read_bytes()


def test_competing_processes_keep_every_previous_run(tmp_path):
    code = """import sys
from hx.model import Graph
from hx.project import save_extraction
root, sequence = sys.argv[1], int(sys.argv[2])
g = Graph(root=root, lang='c', entry='c:src/a.c::f', meta={'entry_arg': 'src/a.c:f', 'sequence': sequence})
save_extraction(root, 'src/a.c:f', g, refresh_default=True)
"""
    processes = [subprocess.Popen([sys.executable, "-c", code, str(tmp_path), str(i)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(6)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, (stdout, stderr)
    snapshots = project.list_history(str(tmp_path), ENTRY)
    values = {project.load_graph(h["path"])["meta"]["sequence"] for h in snapshots}
    values.add(project.load_graph(str(current(tmp_path)))["meta"]["sequence"])
    assert len(snapshots) == 5 and values == set(range(6))


def test_old_identifiers_and_iso_queries_use_actual_generation_time(tmp_path):
    root = str(tmp_path)
    history = Path(project.history_dir(root, ENTRY))
    history.mkdir(parents=True)
    legacy = history / "2026-10-14T05-00-00+02-00.json"
    graph(root, generated="2026-10-14T05:00:00+02:00").save(str(legacy))
    payload = legacy.read_bytes()
    project.save_extraction(root, ENTRY, graph(root, generated="2026-10-14T02:00:00Z"))
    project.save_extraction(root, ENTRY, graph(root, generated="2026-10-14T04:00:00Z"))
    records = project.list_history(root, ENTRY)
    assert records[-1]["ts"] == legacy.stem
    assert project.resolve_history(root, ENTRY, legacy.stem)["path"] == str(legacy)
    assert project.resolve_history(root, ENTRY, "2026-10-14T02:30:00Z")["generated"] == "2026-10-14T02:00:00Z"
    assert project.resolve_history(root, ENTRY, "2026-10-14T03:30:00Z")["path"] == str(legacy)
    assert legacy.read_bytes() == payload and records[-1]["provenance"] is None


def test_cli_mcp_viewer_and_update_share_one_history(tmp_path):
    from fastapi.testclient import TestClient
    from mcp.client import Client
    from hx.mcp_server import build_server
    from hx.serve.app import create_app
    (tmp_path / ".github").mkdir()
    source = tmp_path / "deck.sp"
    source.write_text("Shared workflow\nr1 in 0 1k\n.end\n")
    entry = "deck.sp:."
    command = subprocess.run([sys.executable, "-m", "hx.cli", "extract", entry], cwd=tmp_path,
                             capture_output=True, text=True, timeout=20)
    assert command.returncode == 0, command.stderr
    canonical = current(tmp_path, entry)
    default = tmp_path / ".hx/graph.json"
    cli_bytes = canonical.read_bytes()

    async def via_mcp():
        async with Client(build_server(str(tmp_path))) as client:
            return await client.call_tool("extract", {"entry": entry})

    result = asyncio.run(via_mcp())
    assert not result.is_error
    mcp_bytes = canonical.read_bytes()
    assert mcp_bytes != cli_bytes and default.read_bytes() == mcp_bytes
    assert [Path(h["path"]).read_bytes() for h in project.list_history(str(tmp_path), entry)] == [cli_bytes]
    with TestClient(create_app(str(default), poll_interval=0.02)) as client:
        status = client.get("/api/status").json()
        assert status["provenance"]["run_id"] == json.loads(mcp_bytes)["meta"]["provenance"]["run_id"]
        assert all(g["provenance"] for g in client.get("/api/graphs").json())
        assert client.post("/api/snapshot").status_code == 200
        assert client.post("/api/extract").status_code == 202
        deadline = time.monotonic() + 15
        while client.get("/api/status").json()["extracting"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not client.get("/api/status").json()["extracting"]
        assert client.get("/api/status").json()["last_extract_error"] is None
        diff = client.get("/api/diff").json()
        assert diff["since_generated"] and not diff["summary"]["any"]
        assert client.get("/api/diff", params={"since": "not-a-history-point"}).status_code == 400
    viewer_bytes = canonical.read_bytes()
    assert viewer_bytes != mcp_bytes and default.read_bytes() == viewer_bytes
    project.track(str(tmp_path), entry)
    updated = project.update(str(tmp_path))[0]
    assert updated.error is None and default.read_bytes() == canonical.read_bytes()
    history = project.list_history(str(tmp_path), entry)
    assert [Path(h["path"]).read_bytes() for h in history] == [cli_bytes, mcp_bytes, viewer_bytes]


def test_cli_custom_output_has_provenance_without_managed_graphs(tmp_path):
    (tmp_path / ".github").mkdir()
    (tmp_path / "deck.sp").write_text("Standalone workflow\nr1 in 0 1k\n.end\n")
    command = subprocess.run([sys.executable, "-m", "hx.cli", "extract", "deck.sp:.", "-o", "review.json"],
                             cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert command.returncode == 0, command.stderr
    assert json.loads((tmp_path / "review.json").read_bytes())["meta"]["provenance"]["inputs"]["coverage"] == "observed"
    assert not (tmp_path / ".hx/graphs").exists() and not (tmp_path / ".hx/history").exists()
    assert not (tmp_path / ".hx/graph.json").exists()
