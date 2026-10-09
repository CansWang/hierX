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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
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
        self._mtimes = {"graph": self._mtime(self.graph_path), "ann": self._mtime(self.ann_path)}
        self._lock = threading.Lock()

    @staticmethod
    def _mtime(p: str) -> Optional[int]:
        try:
            return os.stat(p).st_mtime_ns
        except OSError:
            return None

    def load_graph(self) -> dict:
        try:
            with open(self.graph_path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            raise HTTPException(404, f"graph not found: {self.graph_path}. Run `hx extract` first.")
        except ValueError as e:
            raise HTTPException(500, f"graph is not valid JSON: {e}")

    def effective_root(self) -> Optional[str]:
        if self.root:
            return self.root
        try:
            return os.path.abspath(self.load_graph().get("root") or "")
        except HTTPException:
            return None

    # -- events -------------------------------------------------------------
    def broadcast(self, event: str, data: Any = None) -> None:
        msg = (event, data)
        if self.loop is None:
            return
        for q in list(self.subscribers):
            self.loop.call_soon_threadsafe(q.put_nowait, msg)

    def note_written(self, which: str) -> None:
        """Remember our own write so the file watcher does not echo it back as an external change."""
        path = self.graph_path if which == "graph" else self.ann_path
        self._mtimes[which] = self._mtime(path)

    def poll_files(self) -> list[str]:
        changed = []
        for which, path in (("graph", self.graph_path), ("ann", self.ann_path)):
            m = self._mtime(path)
            if m != self._mtimes[which]:
                self._mtimes[which] = m
                changed.append(which)
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
    def status() -> dict:
        g = None
        try:
            g = st.load_graph()
        except HTTPException:
            pass
        return {"graph_path": st.graph_path, "annotations_path": st.ann_path, "root": st.effective_root(),
                "entry": g.get("entry") if g else None, "generated": g.get("generated") if g else None,
                "rev": st.rev, "extracting": st.extracting, "allow_extract": st.allow_extract,
                "last_extract_error": st.last_extract_error}

    @app.get("/api/graph")
    def graph() -> FileResponse:
        if not os.path.exists(st.graph_path):
            raise HTTPException(404, f"graph not found: {st.graph_path}. Run `hx extract` first.")
        return FileResponse(st.graph_path, media_type="application/json")

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
    def source(file: str, line: int = 1, span: int = 40) -> dict:
        root = st.effective_root()
        if not root:
            raise HTTPException(400, "no project root known")
        target = os.path.abspath(file if os.path.isabs(file) else os.path.join(root, file))
        if os.path.commonpath([root, target]) != root:
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
    async def extract() -> JSONResponse:
        if not st.allow_extract:
            raise HTTPException(403, "re-extraction disabled (--no-extract)")
        if st.extracting:
            return JSONResponse({"status": "already-running"}, status_code=409)
        g = st.load_graph()
        args = (g.get("meta") or {}).get("extract_args")
        if not args:
            raise HTTPException(400, "graph has no meta.extract_args; re-run `hx extract` from the CLI once")
        st.extracting = True
        st.last_extract_error = None
        st.broadcast("extract-start", {"entry": args.get("entry")})
        asyncio.create_task(asyncio.to_thread(_run_extract, st, args))
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


def _run_extract(st: State, args: dict) -> None:
    try:
        from ..api import extract as do_extract
        kwargs = {k: v for k, v in args.items() if k != "entry"}
        graph = do_extract(args["entry"], **kwargs)
        graph.save(st.graph_path)
        st.note_written("graph")
        st.broadcast("extract-done", {"entry": graph.entry, "nodes": len(graph.nodes)})
        st.broadcast("graph", {"reason": "extract"})
    except Exception as e:  # noqa: BLE001 - reported to the UI
        st.last_extract_error = f"{type(e).__name__}: {e}"
        st.broadcast("extract-error", {"error": st.last_extract_error})
    finally:
        st.extracting = False


async def _watch_files(st: State, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        for which in st.poll_files():
            if which == "graph":
                st.broadcast("graph", {"reason": "file-changed"})
            else:
                st.rev += 1
                st.broadcast("annotations", {"rev": st.rev, "reason": "file-changed"})
