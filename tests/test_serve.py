import json
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from hx.serve.app import create_app


@pytest.fixture
def served(cproj, extract):
    g = extract(depth=2)
    gp = cproj / ".hx" / "graph.json"
    g.save(str(gp))
    app = create_app(str(gp), poll_interval=0.05)
    with TestClient(app) as c:
        yield c, cproj, app.state.hx


def test_index_and_static(served):
    c, _, st = served
    r = c.get("/")
    assert r.status_code == 200 and 'window.HX_CONFIG = {"mode": "serve", "allow_extract": true, "graph_name": "graph"};' in r.text
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/patch.js").status_code == 200 and "root.hxPatch" in c.get("/static/patch.js").text
    assert c.get("/static/vendor/cytoscape.min.js").status_code == 200
    assert c.get("/api/status").json()["entry"] == "c:src/main.c::app_run"


def test_graph_and_annotations_roundtrip(served):
    c, cproj, st = served
    g = c.get("/api/graph").json()
    assert g["schema"] == "hx/4" and "c:src/dma.c::dma_start" in g["nodes"]
    a = c.get("/api/annotations").json()
    assert a["rev"] == 0 and a["annotations"]["nodes"] == {}
    r = c.patch("/api/annotations", json={"nodes": {"c:src/dma.c::dma_start": {"note": "n", "params": {"ch": {"dir": "out"}}}}})
    assert r.status_code == 200 and r.json()["rev"] == 1
    on_disk = json.load(open(cproj / ".hx" / "annotations.json"))
    assert on_disk["nodes"]["c:src/dma.c::dma_start"]["params"]["ch"]["dir"] == "out"
    r = c.put("/api/annotations", json={"nodes": {"x": {"note": "replaced"}}})
    assert r.json()["rev"] == 2 and list(r.json()["annotations"]["nodes"]) == ["x"]
    assert c.patch("/api/annotations", json=[1, 2]).status_code == 400


def test_delete_patches_persist(served):
    """The exact patches the UI sends for clear-note / un-verify / reset-dir / relayout must delete on disk (review finding H4)."""
    c, cproj, _ = served
    nid = "c:src/dma.c::dma_start"
    c.patch("/api/annotations", json={"nodes": {nid: {"note": "n", "tags": ["t"], "verified_body_hash": "sha1:x", "params": {"ch": {"dir": "out"}}}},
                                      "view": {"pinned_positions": {nid: {"x": 1, "y": 2}, "c:src/main.c::app_run": {"x": 3, "y": 4}}}})
    for patch in ({"nodes": {nid: {"note": None}}}, {"nodes": {nid: {"tags": None}}}, {"nodes": {nid: {"verified_body_hash": None}}},
                  {"nodes": {nid: {"params": {"ch": {"dir": None}}}}}, {"view": {"pinned_positions": None}}):
        assert c.patch("/api/annotations", json=patch).status_code == 200
    doc = c.get("/api/annotations").json()["annotations"]
    assert nid not in doc["nodes"] and doc["view"]["pinned_positions"] == {}
    on_disk = json.load(open(cproj / ".hx" / "annotations.json"))
    assert on_disk["nodes"] == {} and on_disk["view"]["pinned_positions"] == {}


@pytest.mark.parametrize("method", ["put", "patch"])
@pytest.mark.parametrize("body", [b"{", b"", b'"\xff"'])
def test_invalid_annotation_json_has_no_side_effects(served, monkeypatch, method, body):
    client, root, state = served
    client.patch("/api/annotations", json={"nodes": {"n": {"note": "keep"}}})
    path = root / ".hx/annotations.json"
    original, rev = path.read_bytes(), state.rev
    events = []
    monkeypatch.setattr(state, "broadcast", lambda *args: events.append(args))
    response = getattr(client, method)("/api/annotations", content=body,
                                       headers={"content-type": "application/json"})
    assert response.status_code == 400 and "valid JSON" in response.json()["detail"]
    assert path.read_bytes() == original and state.rev == rev and events == []


def test_non_object_annotation_put_keeps_documented_normalization(served):
    client, _, _ = served
    client.patch("/api/annotations", json={"nodes": {"n": {"note": "replace"}}})
    response = client.put("/api/annotations", json=[])
    assert response.status_code == 200 and response.json()["annotations"]["nodes"] == {}


def test_source_confined_to_root(served):
    c, cproj, _ = served
    r = c.get("/api/source", params={"file": "src/dma.c", "line": 1, "span": 2})
    assert r.status_code == 200 and r.json()["lines"][0] == '#include "dma.h"'
    assert c.get("/api/source", params={"file": "../../etc/passwd"}).status_code == 403
    assert c.get("/api/source", params={"file": "/etc/passwd"}).status_code == 403
    assert c.get("/api/source", params={"file": "src/nope.c"}).status_code == 404
    os.symlink("/etc/hostname", cproj / "src" / "escape.c")           # symlink inside the root pointing outside it
    assert c.get("/api/source", params={"file": "src/escape.c"}).status_code == 403
    os.symlink(cproj / "src" / "dma.c", cproj / "src" / "alias.c")   # symlink that stays inside is fine
    assert c.get("/api/source", params={"file": "src/alias.c"}).status_code == 200
    r = c.get("/api/source", params={"file": "src/dma.c", "line": 5, "span": 9999})
    assert len(r.json()["lines"]) <= 400


@pytest.fixture
def live_server(cproj, extract):
    """Real uvicorn in a thread: TestClient buffers whole responses, so SSE needs a live socket."""
    import socket
    import threading
    import uvicorn
    g = extract(depth=2)
    gp = cproj / ".hx" / "graph.json"
    g.save(str(gp))
    app = create_app(str(gp), poll_interval=0.05)
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    assert server.started
    yield f"http://127.0.0.1:{port}", cproj, app.state.hx
    server.should_exit = True
    t.join(timeout=5)


def _events(lines, stop_when, limit=12.0):
    """Collect SSE event names from a shared line iterator until stop_when(seen) or the time limit."""
    seen = []
    t0 = time.time()
    for line in lines:
        if line.startswith("event:"):
            seen.append(line.split(": ", 1)[1])
            if stop_when(seen):
                break
        if time.time() - t0 > limit:
            break
    return seen


def test_sse_hello_and_extract_cycle(live_server):
    import httpx
    base, cproj, st = live_server
    with httpx.Client(base_url=base, timeout=20) as c:
        with c.stream("GET", "/events") as resp:
            lines = resp.iter_lines()
            assert _events(lines, lambda seen: True) == ["hello"]
            assert c.post("/api/extract").status_code == 202
            seen = _events(lines, lambda seen: "graph" in seen)
    assert "extract-start" in seen and "extract-done" in seen and "graph" in seen, seen
    assert st.extracting is False and st.last_extract_error is None


def test_file_watcher_broadcasts_external_changes(live_server):
    import httpx
    base, cproj, st = live_server
    gp = cproj / ".hx" / "graph.json"
    ap = cproj / ".hx" / "annotations.json"
    with httpx.Client(base_url=base, timeout=20) as c:
        with c.stream("GET", "/events") as resp:
            lines = resp.iter_lines()
            assert _events(lines, lambda seen: True) == ["hello"]
            data = json.load(open(gp))
            data["generated"] = "2030-01-01T00:00:00+00:00"
            gp.write_text(json.dumps(data))
            os.utime(gp, (time.time() + 5, time.time() + 5))
            assert _events(lines, lambda seen: "graph" in seen) == ["graph"]
            ap.write_text(json.dumps({"schema": "hx-ann/1", "nodes": {"x": {"note": "external"}}}))
            os.utime(ap, (time.time() + 6, time.time() + 6))
            seen = _events(lines, lambda seen: "annotations" in seen)
            assert seen[-1] == "annotations"
        a = c.get("/api/annotations").json()
        assert a["rev"] >= 1 and a["annotations"]["nodes"]["x"]["note"] == "external"


def test_extract_disabled(cproj, extract):
    g = extract(depth=1)
    gp = cproj / ".hx" / "graph.json"
    g.save(str(gp))
    with TestClient(create_app(str(gp), allow_extract=False)) as c:
        assert c.post("/api/extract").status_code == 403
        assert '"allow_extract": false' in c.get("/").text


def test_graph_poll_reports_each_lifecycle_transition_once(tmp_path):
    from hx.serve.app import State
    primary = tmp_path / ".hx/graph.json"
    graphs = primary.parent / "graphs"
    graphs.mkdir(parents=True)
    primary.write_text("{}")
    tracked = graphs / "tracked.json"
    tracked.write_text("{}")
    state = State(str(primary), str(primary.parent / "annotations.json"), None, True)
    assert state.poll_files() == []
    stamps = {p: p.stat().st_mtime_ns for p in (primary, tracked)}
    primary.unlink()
    tracked.unlink()
    assert state.poll_files() == [("graph", "graph", "file-deleted"), ("graph", "tracked", "file-deleted")]
    assert state.poll_files() == []
    for path, stamp in stamps.items():
        path.write_text("{}")
        os.utime(path, ns=(stamp, stamp))  # recreation counts even with the original timestamp
    assert state.poll_files() == [("graph", "graph", "file-created"), ("graph", "tracked", "file-created")]
    assert state.poll_files() == []
    (graphs / "directory.json").mkdir()
    assert state.poll_files() == []
    os.utime(tracked, ns=(stamps[tracked] + 1000, stamps[tracked] + 1000))
    assert state.poll_files() == [("graph", "tracked", "file-changed")]


def test_deleted_graph_sse_reasons_and_recreation(live_server):
    import httpx
    base, root, _ = live_server
    path = root / ".hx/graph.json"
    saved = path.read_bytes()
    def event(lines):
        name = None
        for line in lines:
            if line.startswith("event: "):
                name = line[7:]
            if line.startswith("data: "):
                return name, json.loads(line[6:])
    with httpx.Client(base_url=base, timeout=10) as client:
        with client.stream("GET", "/events") as response:
            lines = response.iter_lines()
            assert event(lines)[0] == "hello"
            path.unlink()
            assert event(lines) == ("graph", {"reason": "file-deleted", "name": "graph"})
            assert client.get("/api/graph").status_code == 404
            path.write_bytes(saved)
            assert event(lines) == ("graph", {"reason": "file-created", "name": "graph"})
            assert client.get("/api/graph").status_code == 200


def test_multi_graph_history_and_diff(cproj, extract):
    """Tracked graphs under .hx/graphs are listed, diffable against snapshots, and watched."""
    from hx import project
    root = str(cproj)
    project.track(root, "src/main.c:app_run", depth=3, jobs=1)
    project.track(root, "src/hal.c:hal_write32", depth=1, jobs=1)
    project.update(root)
    extract(depth=1).save(str(cproj / ".hx" / "graph.json"))
    with TestClient(create_app(str(cproj / ".hx" / "graph.json"), poll_interval=0.05)) as c:
        names = [g["name"] for g in c.get("/api/graphs").json()]
        assert names == ["graph", project.slug("src/hal.c:hal_write32"), project.slug("src/main.c:app_run")]
        assert c.get("/api/status").json()["graphs"] == names
        g = c.get("/api/graph", params={"name": project.slug("src/hal.c:hal_write32")}).json()
        assert g["entry"] == "c:src/hal.c::hal_write32"
        assert c.get("/api/graph", params={"name": "nope"}).status_code == 404
        h = c.get("/api/history", params={"name": project.slug("src/main.c:app_run")}).json()
        assert h["entry"] == "src/main.c:app_run" and h["snapshots"] == []
        assert c.get("/api/diff", params={"name": project.slug("src/main.c:app_run")}).status_code == 404
        snap = c.post("/api/snapshot", params={"name": project.slug("src/main.c:app_run")}).json()
        assert snap["snapshot"] and len(snap["snapshots"]) == 1
        dma_c = cproj / "src" / "dma.c"
        dma_c.write_text(dma_c.read_text().replace("    g_dma_active++;\n", "    g_dma_active += 1;\n    hal_read32(ch->base);\n"))
        os.utime(dma_c, (time.time() + 5, time.time() + 5))
        project.update(root, ["src/main.c:app_run"])
        d = c.get("/api/diff", params={"name": project.slug("src/main.c:app_run")}).json()
        assert d["schema"] == "hx-diff/1" and d["summary"]["nodes_changed"] == 1 and "calls +hal_read32" in d["markdown"]
        assert d["since"] == snap["snapshot"]
        md = c.get("/api/diff", params={"name": project.slug("src/main.c:app_run"), "format": "md"}).text
        assert md.startswith("# src/main.c:app_run since ")
        src = c.get("/api/source", params={"file": "src/hal.c", "line": 1, "span": 1, "name": project.slug("src/hal.c:hal_write32")}).json()
        assert src["lines"] == ['#include "hal.h"']
    # serve picks a tracked graph when .hx/graph.json is absent
    (cproj / ".hx" / "graph.json").unlink()
    r = subprocess.run([sys.executable, "-c", "import hx.cli,sys; sys.argv=['hx','serve','--port','1']; print(hx.cli._default_graph(None))"],
                       cwd=cproj, capture_output=True, text=True)
    assert r.returncode == 0


def test_extract_endpoint_error_responses_and_failed_runs(served):
    """The documented 409 (a run in progress) and 400 (no replay arguments) responses, and a failing background
    extraction that ends in an `extract-error` recorded on /api/status instead of a hung `extracting` flag."""
    c, cproj, st = served
    st.extracting = True
    r = c.post("/api/extract")
    assert r.status_code == 409 and r.json() == {"status": "already-running"}
    st.extracting = False
    gp = cproj / ".hx" / "graph.json"
    doc = json.loads(gp.read_text())
    args = doc["meta"].pop("extract_args")
    gp.write_text(json.dumps(doc))
    os.utime(gp, (time.time() + 5, time.time() + 5))
    r = c.post("/api/extract")
    assert r.status_code == 400 and "meta.extract_args" in r.json()["detail"]
    doc["meta"]["extract_args"] = dict(args, entry="src/main.c:no_such_function")
    gp.write_text(json.dumps(doc))
    os.utime(gp, (time.time() + 10, time.time() + 10))
    assert c.post("/api/extract").status_code == 202
    for _ in range(100):
        status = c.get("/api/status").json()
        if not status["extracting"]:
            break
        time.sleep(0.1)
    assert not status["extracting"] and status["last_extract_error"].startswith("EntryNotFound")
    assert json.loads(gp.read_text())["entry"] == "c:src/main.c::app_run"              # the failed run replaced nothing


def test_source_without_a_known_root_is_400(tmp_path):
    with TestClient(create_app(str(tmp_path / ".hx" / "graph.json"))) as c:               # no graph yet, no --root
        r = c.get("/api/source", params={"file": "src/main.c"})
        assert r.status_code == 400 and "no project root" in r.json()["detail"]
        assert c.get("/api/graph").status_code == 404
