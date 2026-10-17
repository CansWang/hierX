import json
import subprocess
import sys


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "hx.cli", *args], cwd=cwd, capture_output=True, text=True)


def test_extract_writes_graph_and_summary(cproj):
    r = run(["extract", "src/main.c:app_run", "--depth", "2", "-j", "1", "-o", "out/g.json"], cwd=cproj)
    assert r.returncode == 0, r.stderr
    assert "entry       c:src/main.c::app_run" in r.stdout
    assert "nodes       7" in r.stdout and "output" in r.stdout
    g = json.load(open(cproj / "out" / "g.json"))
    assert g["schema"] == "hx/4" and g["entry"] == "c:src/main.c::app_run"
    assert len(g["nodes"]) == 7
    assert (cproj / ".hx" / "cache").is_dir()


def test_default_output_and_verbose(cproj):
    r = run(["extract", "src/dma.c:dma_start", "--all", "-v", "--no-cache", "-j", "1"], cwd=cproj)
    assert r.returncode == 0, r.stderr
    assert (cproj / ".hx" / "graph.json").exists()
    assert "unresolved  ch->cb" in r.stdout
    assert not (cproj / ".hx" / "cache").exists()


def test_bad_entry_exit_code(cproj):
    r = run(["extract", "src/main.c:nope", "-j", "1"], cwd=cproj)
    assert r.returncode == 2 and "not found" in r.stderr
    r = run(["extract", "no-colon", "-j", "1"], cwd=cproj)
    assert r.returncode == 2 and "<file>:<symbol>" in r.stderr


def test_missing_compile_commands(tmp_path):
    (tmp_path / "a.c").write_text("int f(void){return 0;}\n")
    r = run(["extract", "a.c:f"], cwd=tmp_path)
    assert r.returncode == 2 and "compile_commands.json not found" in r.stderr
