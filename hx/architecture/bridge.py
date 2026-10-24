"""Versioned subprocess boundary around the unmodified upstream D2 compiler."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from ..frontends.base import FrontendError
from ..tools import resolve_tool
from .model import ArchitectureError

PROTOCOL = "hx-d2-bridge/1"
D2_VERSION = "v0.9.0"
D2_COMMIT = "d5a51743b6d5c00f1ec6f8340003f5d5a6ba4eda"


def _require(condition: bool) -> None:
    # Protocol checks must also run under python -O.
    if not condition:
        raise ValueError("invalid bridge fields")


def compile_d2(design: str, root: str | None = None, bridge: str | None = None,
               timeout: float = 30) -> dict:
    """Compile local D2 through an explicitly installed helper; never build/download.

    The helper confines and snapshots imported bytes. Qualified key segments are
    returned by upstream compilation rather than reconstructed from dotted text.
    """
    try:
        executable = resolve_tool("d2_bridge", bridge)
        source = Path(design).resolve(strict=True)
        project = Path(root).resolve(strict=True) if root else source.parent
        entry = source.relative_to(project).as_posix()
        proc = subprocess.run([executable, "--root", str(project), "--input", entry],
                              text=True, capture_output=True, timeout=timeout)
    except (OSError, ValueError, FrontendError, subprocess.TimeoutExpired) as exc:
        raise ArchitectureError(f"D2 bridge: {exc}") from exc
    try:
        data = json.loads(proc.stdout)
        _require(isinstance(data, dict))
        _require((data["protocol"], data["d2_version"], data["d2_commit"]) == (PROTOCOL, D2_VERSION, D2_COMMIT))
        _require(isinstance(data["ok"], bool) and proc.returncode == (0 if data["ok"] else 1))
        for name in ("objects", "edges", "inputs", "diagnostics"):
            _require(isinstance(data[name], list) and all(isinstance(row, dict) for row in data[name]))
        _require(isinstance(data["boards"], bool))
        _require(isinstance(data["presentation"], bool))
        _require(data["ok"] or data["diagnostics"])
        for row in data["objects"]:
            _require(all(isinstance(row[k], str) for k in ("id", "parent", "label", "link")))
            _require(isinstance(row["path"], list) and all(isinstance(p, str) for p in row["path"]))
            _require(row["classes"] is None or (isinstance(row["classes"], list) and all(isinstance(c, str) for c in row["classes"])))
            _require(isinstance(row["sources"], list))
        for row in data["edges"]:
            _require(all(isinstance(row[k], str) for k in ("id", "source", "target", "label")))
            _require(isinstance(row["forward"], bool))
            _require(row["classes"] is None or (isinstance(row["classes"], list) and all(isinstance(c, str) for c in row["classes"])))
            _require(isinstance(row["sources"], list))
        for row in data["diagnostics"]:
            _require(isinstance(row["code"], str) and isinstance(row["message"], str))
        for row in data["inputs"]:
            _require(isinstance(row["file"], str) and isinstance(row["sha256"], str))
    except (ValueError, TypeError, KeyError) as exc:
        detail = proc.stderr.strip()[:1000]
        raise ArchitectureError(f"D2 bridge returned invalid output or an incompatible protocol (exit {proc.returncode})" +
                                (f": {detail}" if detail else "")) from exc
    return data
