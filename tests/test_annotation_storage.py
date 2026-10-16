"""Project annotation ownership, compatibility import, and read-only export."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
from mcp.client import Client
import pytest

from hx import annotations as A, cli, project
from hx.export import export_file
from hx.mcp_server import build_server
from hx.model import Graph
from hx.paths import select_graph
from hx.serve.app import create_app


def saved_graph(path, root):
    Graph(root=str(root), lang="c", entry="c:a.c::f", meta={"entry_arg": "a.c:f"}).save(str(path))
    return path


def notes(path, text="legacy note", *, versioned=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"nodes": {"c:a.c::f": {"note": text}}, "extra": "preserved during import"}
    if versioned:
        doc["schema"] = "hx-ann/1"
    payload = json.dumps(doc, indent=3).encode() + b"\n"
    path.write_bytes(payload)
    return payload


@pytest.mark.parametrize("relative", ["graph.json", "graphs/a.json", "history/a/old.json", "custom/review.json"])
def test_managed_graphs_use_their_state_location(tmp_path, relative):
    root = tmp_path / "project"
    graph = saved_graph(root / ".hx" / relative, tmp_path / "different-source-root")
    app = create_app(str(graph), root=str(tmp_path / "source-override"))
    assert app.state.hx.ann_path == str(root / ".hx/annotations.json")
    assert app.state.hx.project_root() == str(root)
    assert not (root / ".hx/annotations.json").exists()


def test_standalone_and_explicit_paths_preserve_existing_defaults(tmp_path, monkeypatch):
    graph = saved_graph(tmp_path / "review/g.json", tmp_path / "source")
    assert A.resolve_path(str(graph)) == str(graph.parent / "annotations.json")
    assert create_app(str(graph)).state.hx.ann_path == str(graph.parent / "annotations.json")
    managed = saved_graph(tmp_path / ".hx/graphs/g.json", tmp_path)
    notes(managed.parent / "annotations.json")
    notes(tmp_path / ".hx/history/g/annotations.json", "competing notes")
    monkeypatch.chdir(tmp_path)
    app = create_app(str(managed), annotations_path="explicit.json")
    assert app.state.hx.ann_path == str(tmp_path / "explicit.json")
    assert not (tmp_path / ".hx/annotations.json").exists()


def test_file_and_state_directory_symlinks(tmp_path):
    root = tmp_path / "project"
    graph = saved_graph(root / ".hx/graphs/a.json", root)
    link = tmp_path / "alias.json"
    link.symlink_to(graph)
    assert A.resolve_path(str(link)) == str(root / ".hx/annotations.json")
    elsewhere = tmp_path / "state-storage"
    elsewhere.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (other / ".hx").symlink_to(elsewhere, target_is_directory=True)
    graph = saved_graph(other / ".hx/graphs/a.json", other)
    legacy = graph.parent / "annotations.json"
    payload = notes(legacy)
    canonical = Path(A.prepare_file(str(graph), import_legacy=True))
    assert canonical.resolve() == elsewhere / "annotations.json"
    assert canonical.read_bytes() == payload and legacy.read_bytes() == payload


@pytest.mark.parametrize("relative", ["graphs/annotations.json", "history/a/annotations.json", "custom/annotations.json"])
def test_one_legacy_file_is_copied_exactly_once(tmp_path, relative):
    selected = "custom/g.json" if relative.startswith("custom/") else "graphs/g.json"
    graph = saved_graph(tmp_path / ".hx" / selected, tmp_path)
    legacy = tmp_path / ".hx" / relative
    payload = notes(legacy, versioned=False)
    canonical = tmp_path / ".hx/annotations.json"
    assert A.resolve_path(str(graph)) == str(canonical) and not canonical.exists()
    assert A.prepare_file(str(graph)) == str(legacy) and not canonical.exists()
    assert A.prepare_file(str(graph), import_legacy=True) == str(canonical)
    assert canonical.read_bytes() == payload and legacy.read_bytes() == payload
    A.patch_file(str(canonical), {"nodes": {"c:a.c::f": {"note": "new shared note"}}})
    A.prepare_file(str(graph), import_legacy=True)
    assert A.load(str(canonical))["nodes"]["c:a.c::f"]["note"] == "new shared note"
    assert legacy.read_bytes() == payload


def test_existing_canonical_wins_over_conflicting_legacy_files(tmp_path):
    graph = saved_graph(tmp_path / ".hx/graphs/g.json", tmp_path)
    canonical = tmp_path / ".hx/annotations.json"
    payload = notes(canonical, "canonical note")
    notes(graph.parent / "annotations.json", "sidecar note")
    notes(tmp_path / ".hx/history/g/annotations.json", "historical note")
    assert A.prepare_file(str(graph), import_legacy=True) == str(canonical)
    assert canonical.read_bytes() == payload


def test_aliases_of_one_legacy_file_count_as_one_source(tmp_path):
    graph = saved_graph(tmp_path / ".hx/graphs/g.json", tmp_path)
    legacy = graph.parent / "annotations.json"
    payload = notes(legacy)
    alias = tmp_path / ".hx/history/g/annotations.json"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(legacy)
    shared = Path(A.prepare_file(str(graph), import_legacy=True))
    assert shared.read_bytes() == payload
    assert legacy.read_bytes() == payload and alias.is_symlink()


def test_competing_legacy_files_require_explicit_selection(tmp_path):
    graph = saved_graph(tmp_path / ".hx/graphs/g.json", tmp_path)
    one = graph.parent / "annotations.json"
    two = tmp_path / ".hx/history/g/annotations.json"
    payload = notes(one)
    notes(two)  # even equal content in distinct files is not an implicit merge policy
    for import_legacy in (False, True):
        with pytest.raises(ValueError, match="multiple legacy annotation files") as error:
            A.prepare_file(str(graph), import_legacy=import_legacy)
        assert str(one) in str(error.value) and str(two) in str(error.value)
    assert not (tmp_path / ".hx/annotations.json").exists()
    assert one.read_bytes() == payload and two.read_bytes() == payload
    assert A.prepare_file(str(graph), str(one), import_legacy=True) == str(one)


def test_only_a_reserved_note_file_does_not_satisfy_graph_discovery(tmp_path):
    notes(tmp_path / ".hx/graphs/annotations.json")
    with pytest.raises(ValueError, match="no graph"):
        select_graph(None, cwd=tmp_path)


@pytest.mark.parametrize("payload", [b"not JSON", b"[]", b'{"schema":"hx/3"}', b'{"schema":"hx-ann/99"}'])
def test_invalid_legacy_notes_are_not_imported(tmp_path, payload):
    graph = saved_graph(tmp_path / ".hx/graphs/g.json", tmp_path)
    legacy = graph.parent / "annotations.json"
    legacy.write_bytes(payload)
    with pytest.raises(ValueError, match="original file retained"):
        A.prepare_file(str(graph), import_legacy=True)
    assert not (tmp_path / ".hx/annotations.json").exists() and legacy.read_bytes() == payload


def test_unreadable_source_does_not_create_shared_notes(tmp_path, monkeypatch):
    import builtins
    graph = saved_graph(tmp_path / ".hx/graphs/g.json", tmp_path)
    legacy = graph.parent / "annotations.json"
    notes(legacy)
    real_open = builtins.open

    def fail(path, *args, **kwargs):
        if Path(path) == legacy:
            raise PermissionError("injected read failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail)
    with pytest.raises(ValueError, match="injected read failure"):
        A.prepare_file(str(graph), import_legacy=True)
    assert not (tmp_path / ".hx/annotations.json").exists()


def test_concurrent_initializers_and_note_edits_never_reset_shared_file(tmp_path):
    graph = saved_graph(tmp_path / ".hx/graphs/g.json", tmp_path)
    legacy = graph.parent / "annotations.json"
    original = notes(legacy)

    def initialize_and_edit(index):
        path = A.prepare_file(str(graph), import_legacy=True)
        A.patch_file(path, {"nodes": {f"node-{index}": {"note": str(index)}}})

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(initialize_and_edit, range(12)))
    shared = A.load(str(tmp_path / ".hx/annotations.json"))
    assert all(f"node-{i}" in shared["nodes"] for i in range(12))
    assert shared["nodes"]["c:a.c::f"]["note"] == "legacy note"
    assert legacy.read_bytes() == original


def test_independent_processes_import_without_overwriting_edits(tmp_path):
    graph = saved_graph(tmp_path / ".hx/graphs/g.json", tmp_path)
    notes(graph.parent / "annotations.json")
    code = """import sys
from hx import annotations as A
path=A.prepare_file(sys.argv[1],import_legacy=True)
A.patch_file(path,{'nodes':{sys.argv[2]:{'note':'saved'}}})
"""
    processes = [subprocess.Popen([sys.executable, "-c", code, str(graph), f"node-{i}"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(5)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, (stdout, stderr)
    shared = A.load(str(tmp_path / ".hx/annotations.json"))
    assert all(f"node-{i}" in shared["nodes"] for i in range(5))


def test_export_reads_legacy_without_importing_and_then_prefers_shared(tmp_path):
    graph = saved_graph(tmp_path / ".hx/graphs/g.json", tmp_path)
    legacy = graph.parent / "annotations.json"
    payload = notes(legacy, "exported legacy note")
    canonical = tmp_path / ".hx/annotations.json"
    output = tmp_path / "view.html"
    export_file(str(graph), str(output))
    assert "exported legacy note" in output.read_text()
    assert not canonical.exists() and not canonical.with_suffix(".json.lock").exists()
    assert legacy.read_bytes() == payload
    notes(canonical, "exported shared note")
    export_file(str(graph), str(output))
    assert "exported shared note" in output.read_text() and "exported legacy note" not in output.read_text()
    export_file(str(graph), str(output), str(legacy))
    assert "exported legacy note" in output.read_text()


def test_reserved_notes_are_not_graphs_or_history(tmp_path):
    graph = saved_graph(tmp_path / ".hx/graphs/z.json", tmp_path)
    notes(graph.parent / "annotations.json")
    A.patch_file(str(graph.parent / "annotations.json"), {"meta": {"deps": ["not-a-graph-dependency"]}})
    history = Path(project.history_dir(str(tmp_path), "a.c:f"))
    notes(history / "annotations.json")
    saved_graph(history / "snapshot.json", tmp_path)
    assert select_graph(None, cwd=tmp_path) == str(graph)
    # Explicit override avoids importing two competing note sources while examining the picker.
    app = create_app(str(graph), annotations_path=str(graph.parent / "annotations.json"))
    assert [g["name"] for g in app.state.hx.graph_list()] == ["z"]
    assert [g["name"] for g in project.find_graphs(str(tmp_path))] == ["z"]
    assert [h["ts"] for h in project.list_history(str(tmp_path), "a.c:f")] == ["snapshot"]
    assert project.dependency_files(str(tmp_path)) == {}
    project.prune_history(str(tmp_path), "a.c:f", 0)
    assert (history / "annotations.json").exists()


def test_conflicting_notes_fail_cli_initialization_without_starting_services(tmp_path, monkeypatch, capsys):
    graph = saved_graph(tmp_path / ".hx/graphs/g.json", tmp_path)
    notes(graph.parent / "annotations.json")
    notes(tmp_path / ".hx/history/g/annotations.json")
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: pytest.fail("server must not start"))
    assert cli.main(["serve", str(graph)]) == 2
    assert "multiple legacy" in capsys.readouterr().err
    output = tmp_path / "view.html"
    assert cli.main(["export", str(graph), "-o", str(output)]) == 2
    assert not output.exists()
    capsys.readouterr()
    assert cli.main(["mcp", "--root", str(tmp_path)]) == 2
    result = capsys.readouterr()
    assert result.out == "" and "multiple legacy" in result.err
    assert not (tmp_path / ".hx/annotations.json").exists()


def test_viewer_and_mcp_read_and_write_the_same_project_notes(cproj, extract):
    graph = cproj / ".hx/graphs/main.json"
    extract().save(str(graph))
    legacy = graph.parent / "annotations.json"
    original = notes(legacy)
    server = build_server(str(cproj))
    assert (cproj / ".hx/annotations.json").read_bytes() == original
    with TestClient(create_app(str(graph))) as viewer:
        nid = "c:src/dma.c::dma_start"

        async def edit_and_read():
            async with Client(server) as client:
                await client.call_tool("annotate", {"id": nid, "note": "shared MCP note"})
                shared = viewer.get("/api/annotations").json()["annotations"]
                assert shared["nodes"][nid]["note"] == "shared MCP note"
                assert viewer.patch("/api/annotations", json={"nodes": {nid: {"note": "shared viewer note"}}}).status_code == 200
                result = await client.call_tool("get_function", {"id": nid})
                return "\n".join(part.text for part in result.content if hasattr(part, "text"))

        assert "shared viewer note" in asyncio.run(edit_and_read())
    assert legacy.read_bytes() == original


def test_migration_conflicts_leave_current_graphs_and_notes_untouched(cproj):
    entry = "src/main.c:app_run"
    project.track(str(cproj), entry, jobs=1)
    assert project.update(str(cproj))[0].error is None
    graph = Path(project.graph_path(str(cproj), entry))
    original_graph = graph.read_bytes()
    notes(graph.parent / "annotations.json")
    notes(cproj / ".hx/history/other/annotations.json", "other notes")
    result = project.migrate(str(cproj))
    assert result["status"] == "failed" and result["failed"][0]["entry"] == "annotations"
    assert graph.read_bytes() == original_graph
    assert not (cproj / ".hx/annotations.json").exists()
    assert project.list_history(str(cproj), entry) == []
