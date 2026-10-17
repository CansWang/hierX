"""Execute the marked tutorial commands against disposable copies of their inputs."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from examples.prepare import prepare
from hx import annotations, project
from hx.api import extract
from hx.model import Graph
from hx.serve.app import create_app
from fastapi.testclient import TestClient
from conftest import require_tool

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def blocks(page):
    return dict(re.findall(r"<!-- hx:test ([\w-]+) -->\n```bash\n(.*?)\n```", (DOCS / page).read_text(encoding="utf-8"), re.S))


def run_block(page, name, workspace):
    script = blocks(page)[name]
    env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    result = subprocess.run(["bash", "-eu", "-o", "pipefail", "-c", script], cwd=workspace,
                            env=env, text=True, capture_output=True, timeout=180)
    assert result.returncode == 0, f"{page} ({name})\n{result.stdout}\n{result.stderr}"
    return result.stdout


def test_prepare_refuses_to_overwrite(tmp_path):
    workspace = prepare("c", tmp_path / "c")
    database = json.loads((workspace / "build/compile_commands.json").read_text())
    assert database and all(Path(row["directory"]) == workspace for row in database)
    assert all((workspace / row["file"]).is_file() for row in database)
    marker = workspace / "keep.txt"
    marker.write_text("reader work")
    with pytest.raises(FileExistsError):
        prepare("c", workspace)
    assert marker.read_text() == "reader work"


def test_netlist_tutorial_and_annotations(tmp_path):
    workspace = prepare("netlist", tmp_path / "netlist")
    page = "tutorials/netlists.md"
    run_block(page, "netlist-extract", workspace)
    graph = Graph.load(str(workspace / ".hx/graph.json"))
    assert graph.entry == "sp:ota.sp::(deck) ota.sp"
    assert graph.nodes["sp:ota.sp::xa"].kind == "instance"
    assert graph.nodes["sp:ota.sp::xa.m_load_1"].precision == "syntax"
    queries = run_block(page, "netlist-queries", workspace)
    assert queries.startswith("net outa (") and '"key": "/five_t_opamp"' in queries and "sp:ota.sp::xa" in queries
    run_block(page, "netlist-entries", workspace)
    assert Graph.load(str(workspace / ".hx/library.json")).entry.endswith("::@nch_wrap")
    run_block(page, "netlist-track", workspace)
    assert project.list_history(str(workspace), "ota.sp:.")
    html = (workspace / ".hx/review.html").read_text()
    assert 'id="hx-graph"' in html and "xa.m_load_1" in html

    # The same API operations described for C notes work with a device graph.
    app = create_app(str(workspace / ".hx/graph.json"), root=str(workspace))
    node = "sp:ota.sp::xa.m_load_1"
    with TestClient(app) as client:
        assert client.patch("/api/annotations", json={"nodes": {node: {"note": "Reviewed", "tags": ["analog"]}}}).status_code == 200
        assert client.patch("/api/annotations", json={"nodes": {node: {"note": None}}}).status_code == 200
    saved = annotations.load(str(workspace / ".hx/annotations.json"))
    assert saved["nodes"][node] == {"tags": ["analog"]}
    # Re-extracting preserves separately stored notes/tags.
    extract("ota.sp:.", root=str(workspace)).save(str(workspace / ".hx/graph.json"))
    assert annotations.load(str(workspace / ".hx/annotations.json")) == saved
    run_block(page, "netlist-discovery", workspace)
    assert (workspace / "review/review.html").is_file()
    assert not (workspace / "review/.hx").exists()
    assert Graph.load(str(workspace / ".hx/graph.json")).root == str(workspace)


def test_python_scripting_tutorial(tmp_path):
    workspace = prepare("netlist", tmp_path / "api")
    original = (workspace / "ota.sp").read_text()
    result = subprocess.run([sys.executable, str(ROOT / "examples/inspect_graph.py")], cwd=workspace,
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Saved .hx/before.json" in result.stdout
    before = Graph.load(str(workspace / ".hx/before.json"))
    after = Graph.load(str(workspace / ".hx/after.json"))
    assert before.nodes["sp:ota.sp::rl"].body_hash != after.nodes["sp:ota.sp::rl"].body_hash
    assert (workspace / ".hx/review.html").is_file()
    assert (workspace / "ota.sp").read_text() == original


def test_agent_setup_commands(tmp_path):
    workspace = prepare("netlist", tmp_path / "agent")
    output = run_block("tutorials/agents.md", "agents-prepare", workspace)
    assert '"mcpServers"' in output and str(workspace) in output
    assert len(project.find_graphs(str(workspace))) == 1


def test_c_toolchain_tutorial(tmp_path):
    require_tool("clang")
    require_tool("gcc")
    workspace = prepare("c", tmp_path / "c")
    page = "tutorials/c-review.md"
    run_block(page, "c-extract", workspace)
    before = Graph.load(str(workspace / ".hx/graph.json"))
    assert "c:src/dma.c::dma_start" in before.nodes
    assert any(u.name == "hal_board_init" for u in before.unresolved)
    run_block(page, "c-callers", workspace)
    assert any(n.depth < 0 for n in Graph.load(str(workspace / ".hx/callers.json")).nodes.values())
    run_block(page, "c-track", workspace)
    output = run_block(page, "c-edit", workspace)
    assert "dma_start" in output and "body" in output
    run_block(page, "c-export", workspace)
    assert (workspace / ".hx/review.html").is_file()


@pytest.mark.parametrize(("language", "page", "commands", "entry"), [
    ("cpp", "guides/c-cpp.md", ["cpp-extract"], "hw::run"),
    ("sv", "guides/systemverilog.md", ["sv-extract", "sv-instance"], "top"),
    ("rust", "guides/rust.md", ["rust-extract"], "app_run"),
    ("python", "guides/python.md", ["python-extract"], "app_run"),
])
def test_language_toolchain_guides(tmp_path, language, page, commands, entry, monkeypatch):
    if language == "cpp":
        require_tool("clang")
        require_tool("g++")
    elif language == "sv":
        require_tool("verilator")
    elif language == "rust":
        executable = require_tool("rust-analyzer", "~/.cargo/bin/rust-analyzer")
        # Match the installation guide's cargo PATH setup for Rustup users.
        monkeypatch.setenv("PATH", str(Path(executable).parent) + os.pathsep + os.environ["PATH"])
    workspace = prepare(language, tmp_path / language)
    for name in commands:
        run_block(page, name, workspace)
    graph = Graph.load(str(workspace / ".hx/graph.json"))
    assert graph.nodes[graph.entry].qualname == entry
    assert len(graph.nodes) > 1 and graph.edges


def test_netlist_oracle_tutorial(tmp_path, monkeypatch):
    executable = require_tool("ngspice")
    monkeypatch.setenv("HX_TOOL_NGSPICE", executable)
    workspace = prepare("netlist", tmp_path / "oracle")
    output = run_block("tutorials/netlists.md", "netlist-oracle", workspace)
    assert "agree" in output
