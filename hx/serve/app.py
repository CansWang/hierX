"""FastAPI app behind `hx serve`.

Routes
  GET  /                      viewer
  GET  /static/...            viewer assets (hx/viewer)
  GET  /api/status            paths, entry, revision, extracting flag
  GET  /api/graph             graph.json as-is
  GET  /api/annotations       annotations.json (normalized)
  PUT  /api/annotations       replace whole document
  PATCH /api/annotations      JSON merge patch (null deletes)
  POST /api/extract           re-run extraction with the args stored in graph.meta.extract_args
  GET  /api/source?file&line&span   source lines, confined to the project root
  GET  /events                SSE: graph | annotations | extract-start | extract-done | extract-error | ping
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
import os
import threading
import time
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import annotations as ann_mod

VIEWER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "viewer")


class State:
    def __init__(self, graph_path: str, ann_path: str, root: Optional[str], allow_extract: bool):
        self.graph_path = os.path.abspath(graph_path)
        self.ann_path = os.path.abspath(ann_path)
        self.root = os.path.abspath(root) if root else None
        self.allow_extract = allow_extract
        self.rev = 0                        # bumps on every annotations change made through the API
        self.extracting = False
        self.last_extract_error: Optional[str] = None
        self.subscribers: list[asyncio.Queue] = []
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.graphs_dir = os.path.join(os.path.dirname(self.graph_path), "graphs") if os.path.basename(self.graph_path) == "graph.json" \
            else (os.path.dirname(self.graph_path) if os.path.basename(os.path.dirname(self.graph_path)) == "graphs" else None)
        self._mtimes: dict[str, Optional[int]] = {"ann": self._mtime(self.ann_path)}
        for g in self.graph_list():
            self._mtimes["graph:" + g["name"]] = self._mtime(g["path"])
        self._lock = threading.Lock()

    # -- graphs --------------------------------------------------------------
    def graph_list(self) -> list[dict]:
        """Served graphs: the main one first, then tracked graphs under .hx/graphs."""
        out = []
        seen = set()
        main_name = "graph" if os.path.basename(self.graph_path) == "graph.json" else os.path.splitext(os.path.basename(self.graph_path))[0]
        if os.path.exists(self.graph_path):
            out.append({"name": main_name, "path": self.graph_path})
            seen.add(self.graph_path)
        if self.graphs_dir and os.path.isdir(self.graphs_dir):
            for f in sorted(os.listdir(self.graphs_dir)):
                p = os.path.join(self.graphs_dir, f)
                if f.endswith(".json") and p not in seen:
                    out.append({"name": f[:-5], "path": p})
        return out

    def resolve(self, name: Optional[str]) -> str:
        if not name:
            return self.graph_path
        for g in self.graph_list():
            if g["name"] == name:
                return g["path"]
        raise HTTPException(404, f"unknown graph {name!r}; see /api/graphs")

    @staticmethod
    def _mtime(p: str) -> Optional[int]:
        try:
            return os.stat(p).st_mtime_ns
        except OSError:
            return None

    def load_graph(self, name: Optional[str] = None) -> dict:
        path = self.resolve(name)
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            raise HTTPException(404, f"graph not found: {path}. Run `hx extract` or `hx update` first.")
        except ValueError as e:
            raise HTTPException(500, f"graph is not valid JSON: {e}")

    def effective_root(self, name: Optional[str] = None) -> Optional[str]:
        if self.root:
            return self.root
        try:
            return os.path.abspath(self.load_graph(name).get("root") or "")
        except HTTPException:
            return None

    def project_root(self) -> str:
        """Directory that holds .hx (history/snapshots live there)."""
        d = os.path.dirname(self.graph_path)
        if os.path.basename(d) == "graphs":
            d = os.path.dirname(d)
        return os.path.dirname(d) if os.path.basename(d) == ".hx" else (self.effective_root() or d)

    # -- events -------------------------------------------------------------
    def broadcast(self, event: str, data: Any = None) -> None:
        msg = (event, data)
        if self.loop is None:
            return
        for q in list(self.subscribers):
            self.loop.call_soon_threadsafe(q.put_nowait, msg)

    def note_written(self, which: str, name: Optional[str] = None) -> None:
        """Remember our own write so the file watcher does not echo it back as an external change."""
        if which == "ann":
            self._mtimes["ann"] = self._mtime(self.ann_path)
        else:
            key = "graph:" + (name or self.graph_list()[0]["name"] if self.graph_list() else "graph")
            self._mtimes[key] = self._mtime(self.resolve(name))

    def poll_files(self) -> list[tuple[str, Optional[str]]]:
        """[('ann', None) | ('graph', name)] for every file whose mtime moved since the last poll."""
        changed: list[tuple[str, Optional[str]]] = []
        m = self._mtime(self.ann_path)
        if m != self._mtimes.get("ann"):
            self._mtimes["ann"] = m
            changed.append(("ann", None))
        for g in self.graph_list():
            key = "graph:" + g["name"]
            m = self._mtime(g["path"])
            if m != self._mtimes.get(key):
                self._mtimes[key] = m
                changed.append(("graph", g["name"]))
        return changed


def create_app(graph_path: str, annotations_path: Optional[str] = None, root: Optional[str] = None,
               allow_extract: bool = True, poll_interval: float = 1.0) -> FastAPI:
    ann_path = annotations_path or os.path.join(os.path.dirname(os.path.abspath(graph_path)), "annotations.json")
    st = State(graph_path, ann_path, root, allow_extract)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        st.loop = asyncio.get_running_loop()
        watcher = asyncio.create_task(_watch_files(st, poll_interval))
        try:
            yield
        finally:
            watcher.cancel()

    app = FastAPI(title="hx viewer", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.hx = st

    app.mount("/static", StaticFiles(directory=VIEWER_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        with open(os.path.join(VIEWER_DIR, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        cfg = {"mode": "serve", "allow_extract": st.allow_extract}
        html = html.replace("window.HX_CONFIG = {mode: \"serve\"};", f"window.HX_CONFIG = {json.dumps(cfg)};")
        return HTMLResponse(html)

    @app.get("/api/status")
    def status(name: Optional[str] = None) -> dict:
        g = None
        try:
            g = st.load_graph(name)
        except HTTPException:
            pass
        return {"graph_path": st.resolve(name) if (name or os.path.exists(st.graph_path)) else st.graph_path,
                "annotations_path": st.ann_path, "root": st.effective_root(name),
                "entry": g.get("entry") if g else None, "generated": g.get("generated") if g else None,
                "rev": st.rev, "extracting": st.extracting, "allow_extract": st.allow_extract,
                "last_extract_error": st.last_extract_error, "graphs": [x["name"] for x in st.graph_list()]}

    @app.get("/api/graphs")
    def graphs() -> list[dict]:
        out = []
        for g in st.graph_list():
            try:
                with open(g["path"], encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue
            out.append({"name": g["name"], "entry": d.get("entry"), "entry_arg": (d.get("meta") or {}).get("entry_arg"),
                        "lang": d.get("lang"), "generated": d.get("generated"), "nodes": len(d.get("nodes", {}))})
        return out

    @app.get("/api/graph")
    def graph(name: Optional[str] = None) -> FileResponse:
        path = st.resolve(name)
        if not os.path.exists(path):
            raise HTTPException(404, f"graph not found: {path}. Run `hx extract` first.")
        return FileResponse(path, media_type="application/json")

    def _entry_arg(name: Optional[str]) -> str:
        g = st.load_graph(name)
        return (g.get("meta") or {}).get("entry_arg") or g.get("entry") or "graph"

    @app.get("/api/history")
    def history(name: Optional[str] = None) -> dict:
        from .. import project
        entry = _entry_arg(name)
        return {"entry": entry, "snapshots": project.list_history(st.project_root(), entry)}

    @app.post("/api/snapshot")
    def take_snapshot(name: Optional[str] = None) -> dict:
        from .. import project
        entry = _entry_arg(name)
        path = project.snapshot(st.project_root(), entry, st.resolve(name))
        return {"entry": entry, "snapshot": os.path.basename(path)[:-5] if path else None, "snapshots": project.list_history(st.project_root(), entry)}

    @app.get("/api/diff")
    def diff(name: Optional[str] = None, since: str = "prev", format: str = "json"):
        from .. import project
        from ..diff import diff_graphs, render_markdown
        g = st.load_graph(name)
        entry = (g.get("meta") or {}).get("entry_arg") or g.get("entry") or "graph"
        h = project.resolve_history(st.project_root(), entry, since)
        if not h:
            raise HTTPException(404, "no history for this graph yet; take a baseline first")
        old = project.load_graph(h["path"])
        d = diff_graphs(old, g)
        d["since"] = h["ts"]
        if format == "md":
            return PlainTextResponse(render_markdown(d, g, title=f"{entry} since {h['ts']}"))
        d["markdown"] = render_markdown(d, g, title=f"{entry} since {h['ts']}")
        return d

    @app.get("/api/annotations")
    def get_annotations() -> dict:
        try:
            doc = ann_mod.load(st.ann_path)
        except ValueError as e:
            raise HTTPException(500, str(e))
        return {"rev": st.rev, "annotations": doc}

    @app.put("/api/annotations")
    async def put_annotations(request: Request) -> dict:
        body = await request.json()
        doc = ann_mod.replace_file(st.ann_path, body if isinstance(body, dict) else {})
        st.note_written("ann")
        st.rev += 1
        st.broadcast("annotations", {"rev": st.rev})
        return {"rev": st.rev, "annotations": doc}

    @app.patch("/api/annotations")
    async def patch_annotations(request: Request) -> dict:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "merge patch must be a JSON object")
        doc = ann_mod.patch_file(st.ann_path, body)
        st.note_written("ann")
        st.rev += 1
        st.broadcast("annotations", {"rev": st.rev})
        return {"rev": st.rev, "annotations": doc}

    @app.get("/api/source")
    def source(file: str, line: int = 1, span: int = 40, name: Optional[str] = None) -> dict:
        root = st.effective_root(name)
        if not root:
            raise HTTPException(400, "no project root known")
        # realpath on both sides: a symlink inside the project must not read files outside it (review finding H8)
        real_root = os.path.realpath(root)
        target = os.path.realpath(file if os.path.isabs(file) else os.path.join(root, file))
        if os.path.commonpath([real_root, target]) != real_root:
            raise HTTPException(403, "path outside project root")
        if not os.path.isfile(target):
            raise HTTPException(404, f"no such file: {file}")
        span = max(1, min(int(span), 400))
        start = max(1, int(line))
        lines: list[str] = []
        with open(target, encoding="utf-8", errors="replace") as fh:
            for i, text in enumerate(fh, 1):
                if i < start:
                    continue
                if i >= start + span:
                    break
                lines.append(text.rstrip("\n"))
        return {"file": file, "start": start, "lines": lines}

    @app.post("/api/extract")
    async def extract(name: Optional[str] = None) -> JSONResponse:
        if not st.allow_extract:
            raise HTTPException(403, "re-extraction disabled (--no-extract)")
        if st.extracting:
            return JSONResponse({"status": "already-running"}, status_code=409)
        g = st.load_graph(name)
        args = (g.get("meta") or {}).get("extract_args")
        if not args:
            raise HTTPException(400, "graph has no meta.extract_args; re-run `hx extract` from the CLI once")
        st.extracting = True
        st.last_extract_error = None
        st.broadcast("extract-start", {"entry": args.get("entry"), "name": name})
        asyncio.create_task(asyncio.to_thread(_run_extract, st, args, name))
        return JSONResponse({"status": "started"}, status_code=202)

    @app.get("/events")
    async def events(request: Request) -> StreamingResponse:
        q: asyncio.Queue = asyncio.Queue()
        st.subscribers.append(q)

        async def gen():
            try:
                yield _sse("hello", {"rev": st.rev})
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event, data = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield _sse(event, data)
                    except asyncio.TimeoutError:
                        yield _sse("ping", {"t": time.time()})
            finally:
                if q in st.subscribers:
                    st.subscribers.remove(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _run_extract(st: State, args: dict, name: Optional[str] = None) -> None:
    try:
        from .. import project
        from ..api import extract as do_extract
        kwargs = {k: v for k, v in args.items() if k != "entry"}
        graph = do_extract(args["entry"], **kwargs)
        path = st.resolve(name)
        project.snapshot(st.project_root(), args["entry"], path)   # keep the previous graph so the viewer can diff
        graph.save(path)
        st.note_written("graph", name)
        st.broadcast("extract-done", {"entry": graph.entry, "nodes": len(graph.nodes), "name": name})
        st.broadcast("graph", {"reason": "extract", "name": name})
    except Exception as e:  # noqa: BLE001 - reported to the UI
        st.last_extract_error = f"{type(e).__name__}: {e}"
        st.broadcast("extract-error", {"error": st.last_extract_error})
    finally:
        st.extracting = False


async def _watch_files(st: State, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        for which, name in st.poll_files():
            if which == "graph":
                st.broadcast("graph", {"reason": "file-changed", "name": name})
            else:
                st.rev += 1
                st.broadcast("annotations", {"rev": st.rev, "reason": "file-changed"})
