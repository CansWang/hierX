"""Project boundaries, invocation-independent extraction, and local-first readers."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from hx import cli, project
from hx.api import extract
from hx.model import Graph
from hx.paths import find_repo_root, resolve_project, select_graph


def repo(path):
    (path / ".github").mkdir(parents=True)
    return path


def deck(root, filename="src/deck.sp"):
    source = root / filename
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("Tutorial deck\n.subckt cell a b\nr1 a b 1k\n.ends cell\nx1 in 0 cell\n.end\n")
    return source


def run(args, cwd, stdin=None):
    return subprocess.run([sys.executable, "-m", "hx.cli", *map(str, args)], cwd=cwd,
                          input=stdin, capture_output=True, text=True, timeout=45)


def checked(args, cwd):
    result = run(args, cwd)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def saved_graph(path, root):
    Graph(root=str(root), lang="sp", entry="sp:src/deck.sp::(deck) deck.sp").save(str(path))
    return path


def test_nested_marker_is_a_boundary_even_without_state(tmp_path):
    outer = repo(tmp_path / "outer")
    inner = repo(outer / "component")
    work = inner / "src"
    work.mkdir()
    saved_graph(outer / ".hx/graph.json", outer)
    assert find_repo_root(work) == inner
    with pytest.raises(ValueError, match=".hx directory missing") as error:
        select_graph(None, cwd=work)
    assert str(inner / ".hx") in str(error.value)
    assert not (inner / ".hx").exists() and not (work / ".hx").exists()


@pytest.mark.parametrize("git_marker", ["file", "directory"])
def test_git_metadata_does_not_mark_a_root(tmp_path, git_marker):
    outer = repo(tmp_path / "outer")
    inner = outer / "component"
    inner.mkdir()
    if git_marker == "file":
        (inner / ".git").write_text("gitdir: ../.git/modules/component\n")
    else:
        (inner / ".git").mkdir()
    assert find_repo_root(inner) == outer
    # A .github file also does not count as a directory marker.
    (inner / ".github").write_text("not a marker directory")
    assert find_repo_root(inner) == outer


def test_no_marker_uses_run_directory_even_with_external_source(tmp_path):
    source = deck(tmp_path / "source")
    (source.parent / ".git").mkdir()
    work = tmp_path / "run"
    work.mkdir()
    checked(["extract", f"{source}:."], work)
    graph = Graph.load(str(work / ".hx/graph.json"))
    assert graph.root == str(work)
    assert (work / ".hx/cache").is_dir()
    assert not (source.parent / ".hx").exists()
    assert not (tmp_path / "source/.hx").exists()


@pytest.mark.parametrize("invocation", ["root", "nested", "outside", "other-repo", "symlink"])
def test_extract_uses_real_source_repo_and_stable_entries(tmp_path, invocation):
    outer = repo(tmp_path / "outer")
    root = repo(outer / "component")
    source = deck(root)
    work = tmp_path / "work"
    work.mkdir()
    if invocation == "root":
        work, entry = root, "src/deck.sp:."
    elif invocation == "nested":
        work, entry = source.parent, "deck.sp:."
    else:
        entry = f"{source}:."
        if invocation == "other-repo":
            repo(work)
        elif invocation == "symlink":
            repo(work)
            link = work / "linked.sp"
            link.symlink_to(source)
            entry = "linked.sp:."
    checked(["extract", entry], work)
    graph = Graph.load(str(root / ".hx/graph.json"))
    assert graph.root == str(root)
    assert graph.entry == "sp:src/deck.sp::(deck) deck.sp"
    assert graph.meta["entry_arg"] == "src/deck.sp:."
    assert graph.meta["extract_args"]["entry"] == "src/deck.sp:."
    assert graph.meta["extract_args"]["root"] == str(root)
    assert (root / ".hx/cache").is_dir()
    assert not (outer / ".hx").exists()
    if work != root:
        assert not (work / ".hx").exists()


def test_explicit_dot_keeps_run_state_and_python_default_is_unchanged(tmp_path, monkeypatch):
    root = repo(tmp_path / "repo")
    source = deck(root)
    work = source.parent
    checked(["extract", "deck.sp:.", "--root", "."], work)
    graph = Graph.load(str(work / ".hx/graph.json"))
    assert graph.root == str(work)
    assert graph.meta["entry_arg"] == "deck.sp:."
    assert not (root / ".hx").exists()
    monkeypatch.chdir(work)
    python_graph = extract("deck.sp:.")
    assert python_graph.root == str(work)
    assert python_graph.entry == graph.entry
    # Explicit roots also keep root-relative entries when invoked elsewhere.
    checked(["extract", "src/deck.sp:.", "--root", root], tmp_path)
    assert Graph.load(str(root / ".hx/graph.json")).entry == "sp:src/deck.sp::(deck) deck.sp"


def test_path_options_survive_tracking_and_replay_from_another_directory(tmp_path):
    root = repo(tmp_path / "repo")
    work = root / "work"
    models = work / "models"
    models.mkdir(parents=True)
    library = models / "cell.inc"
    library.write_text(".subckt cell a b\nr1 a b 1k\n.ends cell\n")
    source = deck(root)
    source.write_text('Tutorial deck\n.include "cell.inc"\nx1 in 0 cell\n.end\n')
    args = ["models/cell.inc:@cell", "--deck", "../src/deck.sp", "--search-path", "models"]
    checked(["extract", *args, "-o", "review.json"], work)
    graph = Graph.load(str(work / "review.json"))
    assert graph.entry == "sp:work/models/cell.inc::@cell"
    assert not graph.circuit["diagnostics"]
    assert graph.meta["extract_args"]["deck"] == str(source)
    assert graph.meta["extract_args"]["search_paths"] == [str(models)]
    assert not (root / "review.json").exists()
    checked(["track", *args], work)
    table = project.load_config(str(root))["entries"][0]
    assert table["entry"] == "work/models/cell.inc:@cell"
    assert table["deck"] == str(source) and table["search_paths"] == [str(models)]
    results = json.loads(checked(["update", "--root", root, "--json"], tmp_path).stdout)
    assert len(results) == 1 and results[0]["error"] is None
    replay = extract(**graph.meta["extract_args"])
    assert replay.entry == graph.entry and replay.nodes.keys() == graph.nodes.keys()
    assert not (work / ".hx").exists()


def test_tracking_keys_and_project_commands_share_the_repo(tmp_path):
    root = repo(tmp_path / "repo")
    source = deck(root)
    checked(["track", "deck.sp:.", "--depth", "1"], source.parent)
    checked(["track", "src/deck.sp:.", "--depth", "2"], root)
    tables = project.load_config(str(root))["entries"]
    assert len(tables) == 1 and tables[0]["entry"] == "src/deck.sp:." and tables[0]["depth"] == 2
    assert "src/deck.sp:." in checked(["track", "--list"], source.parent).stdout
    first = json.loads(checked(["update", "deck.sp:.", "--json"], source.parent).stdout)
    assert first[0]["error"] is None and Path(first[0]["graph"]).parent == root / ".hx/graphs"
    checked(["watch", "--once"], source.parent)
    assert "No structural changes" in checked(["diff", "--entry", "deck.sp:."], source.parent).stdout
    config = json.loads(checked(["mcp", "--print-config"], source.parent).stdout)
    assert config["mcpServers"]["hx"]["args"] == ["mcp", "--root", str(root)]
    checked(["hook", "install"], source.parent)
    assert (root / ".claude/settings.json").is_file()
    checked(["migrate"], source.parent)
    checked(["track", "deck.sp:.", "--remove"], source.parent)
    assert not project.load_config(str(root))["entries"]
    assert not (source.parent / ".hx").exists() and not (source.parent / ".claude").exists()


def test_mixed_roots_fail_before_writes_and_explicit_root_allows_batch(tmp_path):
    one, two = repo(tmp_path / "one"), repo(tmp_path / "two")
    entries = [f"{deck(one)}:.", f"{deck(two)}:."]
    result = run(["update", *entries], tmp_path)
    assert result.returncode == 2 and "different project roots" in result.stderr and "--root" in result.stderr
    assert all(not (p / ".hx").exists() for p in (one, two, tmp_path))
    hook = run(["update", *entries, "--hook"], tmp_path, stdin="{}")
    assert hook.returncode == 0 and "different project roots" in hook.stderr
    results = json.loads(checked(["update", *entries, "--root", tmp_path, "--json"], tmp_path).stdout)
    assert len(results) == 2 and all(r["error"] is None for r in results)
    assert all(Path(r["graph"]).parent == tmp_path / ".hx/graphs" for r in results)


def test_project_resolution_is_read_only_and_rejects_malformed_entries(tmp_path):
    root = repo(tmp_path / "repo")
    work = root / "src"
    work.mkdir()
    assert resolve_project(None, ["missing.sp:."], cwd=work) == (str(root), ["src/missing.sp:."])
    with pytest.raises(ValueError, match="<file>:<symbol>"):
        resolve_project(None, ["not-an-entry"], cwd=work)
    assert not (root / ".hx").exists() and not (work / ".hx").exists()


@pytest.mark.parametrize("entry", [r"C:\src\main.rs", "C:/src/main.rs", "C:/src/main.rs:"])
def test_drive_entry_without_symbol_is_rejected_before_discovery(tmp_path, entry):
    from hx.api import split_entry
    with pytest.raises(ValueError, match="<file>:<symbol>"):
        split_entry(entry)
    with pytest.raises(ValueError, match="<file>:<symbol>"):
        resolve_project(None, [entry], cwd=tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("entry,file,symbol", [
    (r"C:\src\main.rs:main", r"C:\src\main.rs", "main"),
    ("C:/src/main.rs:<Item as Trait>::method", "C:/src/main.rs", "<Item as Trait>::method"),
    ("src/main.cpp:hw::run", "src/main.cpp", "hw::run"),
])
def test_qualified_and_drive_entry_symbols_are_preserved(entry, file, symbol):
    from hx.api import split_entry
    assert split_entry(entry) == (file, symbol)


@pytest.mark.parametrize("command", ["serve", "export"])
def test_readers_prefer_local_state_then_first_marked_repo(tmp_path, monkeypatch, command):
    root = repo(tmp_path / "repo")
    work = root / "src"
    work.mkdir()
    remote = saved_graph(root / ".hx/graph.json", root)
    monkeypatch.chdir(work)
    served = []
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: served.append(app))
    args = [command] if command == "serve" else [command, "-o", "review.html"]
    assert cli.main(args) == 0
    if command == "serve":
        assert served[-1].state.hx.graph_path == str(remote)
    else:
        assert (work / "review.html").is_file()
    local = saved_graph(work / ".hx/graph.json", root)
    assert cli.main(args) == 0
    if command == "serve":
        assert served[-1].state.hx.graph_path == str(local)
    assert select_graph(None) == str(local)
    # There is no third choice: empty local state must not fall back.
    local.unlink()
    before = len(served)
    assert cli.main(args) == 2 and len(served) == before


def test_tracked_graph_selection_is_sorted_and_keeps_its_state(tmp_path, monkeypatch):
    root = repo(tmp_path / "repo")
    work = root / "src"
    work.mkdir()
    saved_graph(root / ".hx/graphs/z.json", root)
    chosen = saved_graph(root / ".hx/graphs/a.json", root)
    invalid = root / ".hx/graphs/0.json"
    invalid.mkdir()  # directories are not graph candidates
    assert select_graph(None, cwd=work) == str(chosen)
    invalid.rmdir()
    monkeypatch.chdir(work)
    served = []
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: served.append(app))
    assert cli.main(["serve"]) == 0
    state = served[0].state.hx
    assert state.graph_path == str(chosen)
    assert state.project_root() == str(root)
    assert [g["name"] for g in state.graph_list()] == ["a", "z"]
    assert state.ann_path == str(root / ".hx/annotations.json")
    direct = saved_graph(root / ".hx/graph.json", root)
    assert select_graph(None) == str(direct)


@pytest.mark.parametrize("local_kind", ["absent", "empty", "file", "broken-link"])
def test_missing_or_invalid_state_never_starts_server(tmp_path, monkeypatch, capsys, local_kind):
    outer = repo(tmp_path / "outer")
    root = repo(outer / "component")
    work = root / "src"
    work.mkdir()
    saved_graph(outer / ".hx/graph.json", outer)
    local = work / ".hx"
    if local_kind == "empty":
        local.mkdir()
    elif local_kind == "file":
        local.write_text("invalid state")
    elif local_kind == "broken-link":
        local.symlink_to(tmp_path / "missing")
    monkeypatch.chdir(work)
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: pytest.fail("server must not start"))
    assert cli.main(["serve"]) == 2
    error = capsys.readouterr().err
    assert str(root / ".hx" if local_kind == "absent" else local) in error
    assert "graph path" in error and "--root" in error
    assert not (root / ".hx").exists()


def test_no_marker_reader_errors_without_creating_state(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["serve"]) == 2
    assert cli.main(["export"]) == 2
    assert str(tmp_path / ".hx") in capsys.readouterr().err
    assert not (tmp_path / ".hx").exists()


def test_explicit_graph_and_viewer_root_override_do_not_change_discovery(tmp_path, monkeypatch):
    root = repo(tmp_path / "repo")
    work = root / "src"
    work.mkdir()
    saved_graph(root / ".hx/graph.json", root)
    supplied = saved_graph(work / "custom.json", root)
    monkeypatch.chdir(work)
    served = []
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: served.append(app))
    assert cli.main(["serve", "custom.json", "--root", str(tmp_path), "--annotations", "notes.json"]) == 0
    state = served[-1].state.hx
    assert state.graph_path == str(supplied) and state.root == str(tmp_path)
    assert state.ann_path == str(work / "notes.json")
    assert cli.main(["serve", "missing.json"]) == 2
    assert cli.main(["export", "missing.json"]) == 2
    assert len(served) == 1
    # --root on serve never becomes a graph search location.
    assert cli.main(["serve", "--root", str(tmp_path)]) == 0
    assert served[-1].state.hx.graph_path == str(root / ".hx/graph.json")


def test_tracked_server_command_keeps_invocation_relative_executable(tmp_path):
    root = repo(tmp_path / "repo")
    source = deck(root)
    checked(["track", "deck.sp:.", "--lsp-cmd", "./tools/server --stdio 'two words'"], source.parent)
    table = project.load_config(str(root))["entries"][0]
    assert table["lsp_cmd"] == [str(source.parent / "tools/server"), "--stdio", "two words"]


def test_netlist_check_uses_discovered_root(tmp_path, monkeypatch):
    root = repo(tmp_path / "repo")
    source = deck(root)
    monkeypatch.chdir(source.parent)
    # Isolate the optional simulator while exercising native extraction with the
    # root/entry passed by the real CLI.
    from hx.netlist import check
    graphs = []

    def oracle(entry, *, root, **kwargs):
        graphs.append(extract(entry, root=root))
        return {"status": "agree"}

    monkeypatch.setattr(check, "check_ngspice", oracle)
    assert cli.main(["netlist", "check", "deck.sp:.", "--json"]) == 0
    assert graphs[0].root == str(root)
    assert graphs[0].meta["entry_arg"] == "src/deck.sp:."
    assert (root / ".hx/cache").is_dir() and not (source.parent / ".hx").exists()


def test_c_toolchain_root_keeps_run_relative_compilation_database(cproj):
    from conftest import require_tool
    require_tool("clang")
    require_tool("gcc")
    (cproj / ".github").mkdir()
    checked(["extract", "main.c:app_run", "--compile-commands", "../build", "-j", "1"], cproj / "src")
    graph = Graph.load(str(cproj / ".hx/graph.json"))
    assert graph.entry == "c:src/main.c::app_run" and len(graph.nodes) > 1
    assert graph.meta["extract_args"]["compile_commands"] == str(cproj / "build")
    assert not (cproj / "src/.hx").exists()


def test_sv_toolchain_root_keeps_run_relative_filelist_and_glob(tmp_path):
    from conftest import require_tool
    from examples.prepare import prepare
    require_tool("verilator")
    root = prepare("sv", tmp_path / "repo")
    (root / ".github").mkdir()
    checked(["extract", "top.sv:top", "-f", "../files.f", "--sv-file", "*.sv"], root / "rtl")
    graph = Graph.load(str(root / ".hx/graph.json"))
    assert graph.entry == "sv:rtl/top.sv::top" and len(graph.nodes) > 1
    assert graph.meta["extract_args"]["filelist"] == str(root / "files.f")
    assert graph.meta["extract_args"]["sv_files"] == [str(root / "rtl/*.sv")]
    assert not (root / "rtl/.hx").exists()


def test_c_toolchain_existing_tracked_database_works_from_subdirectory(cproj):
    from conftest import require_tool
    require_tool("clang")
    require_tool("gcc")
    (cproj / ".github").mkdir()
    # This is the relative option spelling saved by earlier CLI versions.
    project.track(str(cproj), "src/main.c:app_run", compile_commands="build", jobs=1)
    results = json.loads(checked(["update", "--json"], cproj / "src").stdout)
    assert len(results) == 1 and results[0]["error"] is None
    assert "c:src/main.c::app_run" in Graph.load(results[0]["graph"]).nodes
    assert project.load_config(str(cproj))["entries"][0]["compile_commands"] == "build"
    assert not (cproj / "src/.hx").exists()


def test_existing_invocation_relative_database_keeps_priority(tmp_path, monkeypatch):
    from hx.frontends.clang_fe import find_compile_commands
    root = repo(tmp_path / "repo")
    work = tmp_path / "work"
    for location in (root, work):
        (location / "build").mkdir(parents=True)
        (location / "build/compile_commands.json").write_text("[]")
    monkeypatch.chdir(work)
    assert find_compile_commands(str(root), "build") == str(work / "build")
