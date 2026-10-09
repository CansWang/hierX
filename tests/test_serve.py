import json
import os
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
    assert r.status_code == 200 and 'window.HX_CONFIG = {"mode": "serve", "allow_extract": true};' in r.text
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/vendor/cytoscape.min.js").status_code == 200
    assert c.get("/api/status").json()["entry"] == "c:src/main.c::app_run"


def test_graph_and_annotations_roundtrip(served):
    c, cproj, st = served
    g = c.get("/api/graph").json()
    assert g["schema"] == "hx/1" and "c:src/dma.c::dma_start" in g["nodes"]
    a = c.get("/api/annotations").json()
    assert a["rev"] == 0 and a["annotations"]["nodes"] == {}
    r = c.patch("/api/annotations", json={"nodes": {"c:src/dma.c::dma_start": {"note": "n", "params": {"ch": {"dir": "out"}}}}})
    assert r.status_code == 200 and r.json()["rev"] == 1
    on_disk = json.load(open(cproj / ".hx" / "annotations.json"))
    assert on_disk["nodes"]["c:src/dma.c::dma_start"]["params"]["ch"]["dir"] == "out"
    r = c.put("/api/annotations", json={"nodes": {"x": {"note": "replaced"}}})
    assert r.json()["rev"] == 2 and list(r.json()["annotations"]["nodes"]) == ["x"]
    assert c.patch("/api/annotations", json=[1, 2]).status_code == 400


def test_source_confined_to_root(served):
    c, cproj, _ = served
    r = c.get("/api/source", params={"file": "src/dma.c", "line": 1, "span": 2})
    assert r.status_code == 200 and r.json()["lines"][0] == '#include "dma.h"'
    assert c.get("/api/source", params={"file": "../../etc/passwd"}).status_code == 403
    assert c.get("/api/source", params={"file": "/etc/passwd"}).status_code == 403
    assert c.get("/api/source", params={"file": "src/nope.c"}).status_code == 404
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
