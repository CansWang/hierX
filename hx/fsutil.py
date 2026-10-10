"""Small filesystem helpers shared by the writers (graphs, config, history, annotations)."""
from __future__ import annotations

import contextlib
import os
from typing import Iterator, Union


def atomic_write(path: str, data: Union[str, bytes], *, encoding: str = "utf-8") -> None:
    """Write `data` to `path` via a temp file + os.replace, so a reader (the viewer, `hx diff`, an agent) never
    sees a half-written file, and a crash leaves the previous version intact."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        if isinstance(data, str):
            with open(tmp, "w", encoding=encoding) as fh:
                fh.write(data)
        else:
            with open(tmp, "wb") as fh:
                fh.write(data)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


@contextlib.contextmanager
def file_lock(path: str) -> Iterator[None]:
    """Cross-process exclusive lock on `<path>.lock` (fcntl where available; a no-op elsewhere). Used around
    read-modify-write of annotations so `hx serve`, `hx mcp` and the CLI do not clobber each other."""
    lock_path = os.path.abspath(path) + ".lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    try:
        import fcntl
    except ImportError:  # Windows: process-local locking only
        yield
        return
    with open(lock_path, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
