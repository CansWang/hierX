"""Small filesystem helpers shared by the writers (graphs, config, history, annotations)."""
from __future__ import annotations

import contextlib
import os
import tempfile
import threading
from typing import Iterator, Union

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def atomic_write(path: str, data: Union[str, bytes], *, encoding: str = "utf-8") -> None:
    """Write `data` to `path` via a temp file + os.replace, so a reader (the viewer, `hx diff`, an agent) never
    sees a half-written file, and a crash leaves the previous version intact."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data.encode(encoding) if isinstance(data, str) else data)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


def atomic_create(path: str, data: bytes) -> None:
    """Publish a complete new file; an existing destination is never replaced."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".snapshot-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.link(tmp, path)  # atomic publication, including an exclusive destination check
    finally:
        os.unlink(tmp)


@contextlib.contextmanager
def file_lock(path: str) -> Iterator[None]:
    """Thread and cross-process exclusive lock on `<path>.lock` (Unix and Windows)."""
    lock_path = os.path.realpath(path) + ".lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(lock_path, threading.Lock())
    with lock, open(lock_path, "a+b") as fh:
        try:
            import fcntl
        except ImportError:
            import msvcrt
            if os.fstat(fh.fileno()).st_size == 0:
                fh.write(b"\0")
                fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
