"""Per-translation-unit summary cache under <root>/.hx/cache/.

Key = sha1(source path + parse args). An entry is valid while every file it
depended on (the source plus all headers it included) still has the same
mtime_ns. That makes re-extraction after an agent edit re-parse only the
translation units that actually changed.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Optional


class TUCache:
    def __init__(self, directory: str, enabled: bool = True):
        self.dir = directory
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        if enabled:
            os.makedirs(directory, exist_ok=True)

    @staticmethod
    def key(file: str, args: list[str]) -> str:
        h = hashlib.sha1()
        h.update(os.path.abspath(file).encode())
        for a in args:
            h.update(b"\0")
            h.update(a.encode("utf-8", "replace"))
        return h.hexdigest()

    def _path(self, file: str, args: list[str]) -> str:
        return os.path.join(self.dir, self.key(file, args) + ".json")

    @staticmethod
    def deps_fresh(deps: dict[str, int]) -> bool:
        for p, m in deps.items():
            try:
                if os.stat(p).st_mtime_ns != m:
                    return False
            except OSError:
                return False
        return True

    def load(self, file: str, args: list[str]) -> Optional[dict]:
        if not self.enabled:
            return None
        p = self._path(file, args)
        try:
            with open(p, encoding="utf-8") as fh:
                entry = json.load(fh)
        except (OSError, ValueError):
            self.misses += 1
            return None
        if not self.deps_fresh(entry.get("deps", {})):
            self.misses += 1
            return None
        self.hits += 1
        return entry["summary"]

    def store(self, file: str, args: list[str], summary: dict) -> None:
        if not self.enabled:
            return
        p = self._path(file, args)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"deps": summary.get("deps", {}), "summary": summary}, fh)
        os.replace(tmp, p)

    @staticmethod
    def snapshot_deps(paths) -> dict[str, int]:
        deps = {}
        for p in paths:
            try:
                deps[p] = os.stat(p).st_mtime_ns
            except OSError:
                continue
        return deps
