"""Pinned repository examples, portable navigation and local gallery workflows."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from fastapi.testclient import TestClient
import jsonschema
import pytest

from d2_bridge.run import Examples, ExampleError, HERE, REPO
from test_architecture import d2_bridge


@pytest.fixture
def examples(tmp_path, d2_bridge):
    base = tmp_path / "relocated checkout with spaces" / "tests" / "d2_bridge"
    shutil.copytree(
        HERE, base, ignore=shutil.ignore_patterns(".generated", "__pycache__")
    )
    return Examples(base, bridge=d2_bridge)


@pytest.mark.parametrize(
    "identity",
    ["codex-paths", "codex-search", "ffmpeg-transcode", "ffmpeg-av-reuse", "hx-review"],
)
def test_repository_case_matches_independent_expectations(examples, identity):
    case = examples.selected(identity)[0]
    graph = examples.prepare()
    doc = examples.document(case, graph)
    result = examples.verify(case, doc)
    assert result["passed"], result
    assert len(doc.bindings) == len(case["blocks"]) + len(case["ports"])
    assert all(b["status"] == "resolved" for b in doc.bindings.values())


def test_navigation_catalog_is_portable_and_explicitly_limited(examples):
    graph = examples.prepare()
    data = json.loads(graph.read_text())
    schema = json.loads((REPO / "hx/schema/hx-4.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(data)
    assert data["root"] == str(examples.base / "sources")
    assert data["lang"] == "mixed" and not data["edges"] and not data["types"]
    assert "navigation-only" in data["meta"]["evidence_limits"]
    assert "provenance" not in data["meta"] and "extract_args" not in data["meta"]
    for node in data["nodes"].values():
        assert (Path(data["root"]) / node["loc"]["file"]).is_file()
        assert not node["calls"] and not node["body_hash"]
        assert node["attrs"]["navigation_only"]


@pytest.mark.parametrize("problem", ["missing", "changed", "range", "duplicate"])
def test_snapshot_and_navigation_damage_are_named_errors(examples, problem):
    navigation = examples.base / "navigation.json"
    records = json.loads(navigation.read_text())
    node = records["records"][0]["node"]
    source = examples.base / "sources" / node["loc"]["file"]
    if problem == "missing":
        source.unlink()
        message = "Missing pinned snapshot"
    elif problem == "changed":
        source.write_bytes(source.read_bytes() + b"\n")
        message = "SHA-256 mismatch"
    else:
        if problem == "range":
            node["loc"]["line"] = 1000000
            message = "Invalid source range"
        else:
            records["records"].append(deepcopy(records["records"][0]))
            message = "Duplicate navigation declaration"
        navigation.write_text(json.dumps(records))
    with pytest.raises(ExampleError, match=message):
        examples.prepare()
    assert not examples.generated.exists()


def test_checks_reject_a_missing_binding_and_changed_endpoint(examples):
    case = examples.selected("ffmpeg-transcode")[0]
    path = examples.base / "cases/ffmpeg-transcode/main.d2"
    original = path.read_text()
    path.write_text(original.replace("::avcodec_send_packet", "::missing_symbol", 1))
    report = examples.check([case])
    assert not report["passed"]
    assert any("Unresolved" in e for e in report["checks"][0]["errors"])
    path.write_text(
        original.replace(
            "demux.packets -> decode.packets", "demux.packets -> mux.packets"
        )
    )
    report = examples.check([case])
    assert not report["passed"]
    assert any("Unexpected connections" in e for e in report["checks"][0]["errors"])


def test_gallery_routes_source_links_and_invalid_reload(examples):
    graph = examples.prepare()
    with TestClient(examples.app(list(examples.cases.values()), graph)) as client:
        index = client.get("/examples")
        assert index.status_code == 200
        for case in examples.cases.values():
            page = client.get("/examples/" + case["id"])
            assert page.status_code == 200
            assert '"status": "resolved"' in page.text
            assert "http://testserver/#kind=node" in page.text
        assert client.get("/").status_code == 200
        assert client.post("/api/extract").status_code == 403
        note = client.patch(
            "/api/annotations", json={"nodes": {"example": {"note": "local review"}}}
        )
        assert note.status_code == 200
        assert client.post("/api/snapshot").status_code == 200
        assert client.get("/examples/missing").status_code == 404
        source = client.get(
            "/api/source", params={"file": "ffmpeg/libavcodec/decode.c", "line": 734}
        )
        assert source.status_code == 200
        assert "avcodec_send_packet" in source.text
        path = examples.base / "cases/codex-paths/main.d2"
        path.write_text("a: {")
        failed = client.get("/examples/codex-paths")
        assert failed.status_code == 200 and '"valid": false' in failed.text
        assert "d2-compile" in failed.text
    assert (examples.generated / ".hx/annotations.json").is_file()
    assert list((examples.generated / ".hx/history").rglob("*.json"))
    assert not list((examples.base / "sources").rglob(".hx"))


def test_export_does_not_edit_snapshots_and_links_are_explicit(examples):
    files = [
        p
        for p in examples.base.rglob("*")
        if p.is_file() and ".generated" not in p.parts
    ]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    cases = list(examples.cases.values())
    index = examples.export(cases)
    assert index == examples.generated / "exports/index.html"
    assert index.read_text().count('<iframe loading="lazy"') == 5
    path = index.parent / "codex-paths.html"
    assert '"code_urls": {}' in path.read_text()
    examples.export(cases[:1], code_url="http://127.0.0.1:8770/")
    assert "http://127.0.0.1:8770/#kind=node" in path.read_text()
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with pytest.raises(ValueError, match="absolute http"):
        examples.export(cases[:1], code_url="javascript:alert(1)")


def test_generated_symlinks_cannot_redirect_output(examples, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    examples.generated.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ExampleError, match="not a symlink"):
        examples.prepare()
    assert not list(outside.iterdir())
    examples.generated.unlink()
    examples.generated.mkdir()
    (examples.generated / "exports").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ExampleError, match="escapes"):
        examples.export(examples.selected("codex-paths"))
    assert not list(outside.iterdir())


def test_wrapper_works_from_an_unrelated_directory_and_reports_unknown_case(tmp_path):
    env = {**os.environ, "PYTHON": sys.executable}
    result = subprocess.run(
        [str(HERE / "run.sh"), "list"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0 and "ffmpeg-av-reuse" in result.stdout
    result = subprocess.run(
        [str(HERE / "run.sh"), "inspect", "unknown"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert (
        result.returncode == 2
        and "Unknown example" in result.stderr
        and "Traceback" not in result.stderr
    )


def test_relocated_wrapper_keeps_source_root_local(examples, tmp_path):
    env = {
        **os.environ,
        "PYTHON": sys.executable,
        "PYTHONPATH": str(REPO),
        "HX_TOOL_D2_BRIDGE": examples.bridge,
    }
    result = subprocess.run(
        [str(examples.base / "run.sh"), "inspect", "hx-review", "--json"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0]["valid"]
    graph = json.loads((examples.generated / ".hx/graph.json").read_text())
    assert graph["root"] == str(examples.base / "sources")


def test_foreground_cli_gallery_opens_requested_url_and_stops_cleanly(
    examples, tmp_path
):
    browser = tmp_path / "record-browser"
    opened = tmp_path / "opened.txt"
    browser.write_text(
        f"#!{sys.executable}\nimport pathlib,sys\npathlib.Path({str(opened)!r}).write_text(sys.argv[1])\n"
    )
    browser.chmod(0o755)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "PYTHON": sys.executable,
        "PYTHONPATH": str(REPO),
        "HX_TOOL_D2_BRIDGE": examples.bridge,
        "BROWSER": f'"{browser}" %s',
    }
    process = subprocess.Popen(
        [str(examples.base / "run.sh"), "gallery", "--port", str(port), "--open"],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(150):
            assert process.poll() is None
            try:
                with urlopen(base + "/examples", timeout=1) as response:
                    assert b"Hx D2 repository examples" in response.read()
                if opened.exists():
                    break
            except OSError:
                pass
            time.sleep(0.025)
        assert opened.read_text() == base + "/examples"
        with urlopen(base + "/examples/hx-review", timeout=5) as response:
            assert (base + "/#kind=node").encode() in response.read()
    finally:
        process.send_signal(signal.SIGINT)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
    assert process.returncode == 0, (stdout, stderr)
    assert "Stop with Ctrl+C" in stdout and "Traceback" not in stderr
