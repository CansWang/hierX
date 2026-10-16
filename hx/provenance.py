"""Observed extraction provenance. Input coverage is deliberately not a replay guarantee."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid
from typing import Any

from . import __version__

CONFIG_NAMES = ("Cargo.toml", "Cargo.lock", "pyrightconfig.json", "pyproject.toml",
                "go.mod", "go.sum", "go.work", "go.work.sum", "CMakeLists.txt")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")


def digest(value: Any) -> str:
    """SHA-256 of canonical JSON (dictionary keys sorted, array order preserved)."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def git_state(source: str) -> dict:
    """Inspect the source's actual worktree without refreshing Git's index."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    # Caller Git environment must not redirect inspection to a different worktree.
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(key, None)

    def run(cwd: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                              env=env, timeout=10)

    state = {"status": "unavailable", "repo_root": None, "commit": None, "dirty": None}
    try:
        found = run(os.path.dirname(os.path.realpath(source)), "rev-parse", "--show-toplevel")
        if found.returncode:
            if b"not a git repository" in found.stderr.lower():
                state["status"] = "no-repo"
            else:
                state["diagnostic"] = found.stderr.decode(errors="replace").strip()
            return state
        repo = os.path.realpath(os.fsdecode(found.stdout).strip())
        state["repo_root"] = repo
        head = run(repo, "rev-parse", "--verify", "HEAD")
        status = run(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                     "--ignore-submodules=none", "--", ".", ":(exclude)**/.hx/**", ":(exclude).hx/**")
        if status.returncode:
            state["diagnostic"] = status.stderr.decode(errors="replace").strip()
            return state
        state.update(status="ok" if head.returncode == 0 else "unborn",
                     commit=head.stdout.decode().strip() if head.returncode == 0 else None,
                     dirty=bool(status.stdout), status_sha256=hashlib.sha256(status.stdout).hexdigest())
    except (OSError, subprocess.SubprocessError) as exc:
        state["diagnostic"] = str(exc)
    return state


def begin(source: str) -> dict:
    return {"version": 1, "run_id": uuid.uuid4().hex, "started": utc_now(),
            "hx_version": __version__, "git": git_state(source)}


def observed_inputs(fe, root: str, source: str, options: dict) -> dict:
    """Hash available dependencies and note changes against frontend observations."""
    diagnostics = []
    expected: dict[str, int | None] = {}
    try:
        expected.update(fe.provenance_inputs())
    except Exception as exc:  # provenance cannot turn a successful extraction into a failure
        diagnostics.append(f"input discovery: {exc}")
    candidates = set(expected)
    candidates.add(source)
    for key in ("compile_commands", "filelist", "deck"):
        value = options.get(key)
        if value:
            path = value if os.path.isabs(value) else os.path.join(root, value)
            if key == "compile_commands" and os.path.isdir(path):
                path = os.path.join(path, "compile_commands.json")
            candidates.add(path)
    # Recognized configurations near documents read by hx; not all server-private inputs.
    for source_path in list(candidates):
        parent = Path(os.path.realpath(source_path)).parent
        boundary = Path(os.path.realpath(root))
        while parent == boundary or boundary in parent.parents:
            candidates.update(str(parent / name) for name in CONFIG_NAMES if (parent / name).is_file())
            if parent == boundary:
                break
            parent = parent.parent
    canonical_expected = {os.path.realpath(p): stamp for p, stamp in expected.items()}
    files = []
    for path in sorted({os.path.realpath(p if os.path.isabs(p) else os.path.join(root, p)) for p in candidates}):
        relative = os.path.relpath(path, os.path.realpath(root))
        label = relative.replace(os.sep, "/") if relative != ".." and not relative.startswith(".." + os.sep) else path
        item = {"path": label, "sha256": None, "status": "ok"}
        try:
            before = os.stat(path)
            sha = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    sha.update(chunk)
            after = os.stat(path)
            changed = (before.st_mtime_ns, before.st_size, before.st_ino) != (after.st_mtime_ns, after.st_size, after.st_ino)
            if path in canonical_expected and canonical_expected[path] != before.st_mtime_ns:
                changed = True
            item.update(sha256=sha.hexdigest(), status="changed" if changed else "ok")
        except FileNotFoundError:
            item["status"] = "missing"
            if path in canonical_expected and canonical_expected[path] is not None:
                item["status"] = "changed"
        except OSError as exc:
            item.update(status="unreadable", diagnostic=str(exc))
        files.append(item)
    files.sort(key=lambda f: f["path"])
    result = {"coverage": "observed", "files": files, "sha256": digest(files),
              "changed_during_extract": any(f["status"] == "changed" for f in files)}
    if diagnostics:
        result["diagnostics"] = diagnostics
    return result


def finish(graph, started: dict, inputs: dict, source: str) -> None:
    """Attach provenance once; saving and snapshots never recompute it."""
    end_git = git_state(source)
    started["git"]["changed_during_extract"] = any(
        started["git"].get(k) != end_git.get(k) for k in ("status", "repo_root", "commit", "status_sha256"))
    if started["git"]["changed_during_extract"]:
        started["git"]["at_completion"] = end_git
    options = {k: v for k, v in graph.meta["extract_args"].items() if k not in ("entry", "root")}
    document = graph.to_dict()
    content = {k: v for k, v in document.items() if k not in ("root", "generated", "meta")}
    started.update(completed=utc_now(), inputs=inputs, options_sha256=digest(options), graph_sha256=digest(content))
    graph.meta["provenance"] = started


def summary(graph: dict) -> dict | None:
    """Small provenance view for graph/history listings; full manifests stay in graphs."""
    provenance = (graph.get("meta") or {}).get("provenance")
    if not provenance:
        return None
    out = {key: provenance.get(key) for key in ("version", "run_id", "started", "completed", "hx_version",
                                                "git", "options_sha256", "graph_sha256")}
    inputs = provenance.get("inputs") or {}
    out["inputs"] = {key: inputs.get(key) for key in ("coverage", "sha256", "changed_during_extract")}
    return out
