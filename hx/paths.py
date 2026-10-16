"""Read-only project and saved-graph discovery for the CLI.

Python APIs continue to use the root their caller supplies. CLI discovery uses
the first .github directory encountered upward, never Git metadata or a process.
"""
from __future__ import annotations

import os
from pathlib import Path
import shlex
from typing import Sequence

from .api import split_entry


def find_repo_root(start: Path) -> Path | None:
    """Find the nearest ancestor (including start) containing a .github directory."""
    start = start.resolve()
    return next((p for p in (start, *start.parents) if (p / ".github").is_dir()), None)


def resolve_project(root: str | None, entries: Sequence[str] = (), *, cwd: Path | None = None) -> tuple[str, list[str]]:
    """Return an absolute CLI root and entries suitable for that root.

    Explicit roots preserve existing entry spelling/interpretation. Otherwise
    entries are invocation-relative, their real source paths determine discovery,
    and persisted entries become root-relative (absolute when outside the root).
    A batch cannot implicitly select several projects. No files are written.
    """
    cwd = cwd or Path.cwd()
    if root is not None:
        return os.path.abspath(cwd / root), list(entries)
    if not entries:
        return str(find_repo_root(cwd) or cwd), []

    sources = []
    roots = set()
    for entry in entries:
        file, symbol = split_entry(entry)
        source = (cwd / file).resolve()
        sources.append((source, symbol))
        roots.add(find_repo_root(source.parent) or cwd)
    if len(roots) != 1:
        raise ValueError("entries resolve to different project roots: " + ", ".join(sorted(map(str, roots)))
                         + "; pass --root to select one project explicitly")
    selected = roots.pop()
    normalized = []
    for source, symbol in sources:
        file = source.relative_to(selected).as_posix() if source.is_relative_to(selected) else str(source)
        normalized.append(f"{file}:{symbol}")
    return str(selected), normalized


def select_graph(path: str | None, *, cwd: Path | None = None) -> str:
    """Select an explicit graph, or local-first .hx state; never create anything.

    An existing local .hx shadows repository state, even if unusable. Repository
    lookup stops at the first .github whether or not that project has a graph.
    """
    cwd = cwd or Path.cwd()
    if path is not None:
        graph = Path(os.path.abspath(cwd / path))
        if not graph.is_file():
            raise ValueError(f"graph file {graph} does not exist or is not a regular file; pass an existing graph path")
        return str(graph)

    local = cwd / ".hx"
    state = local
    searched = [str(local)]
    if not os.path.lexists(local):
        repo = find_repo_root(cwd)
        if repo is None:
            raise ValueError(f"no .hx directory at {local} and no ancestor .github directory; "
                             "run `hx extract` or pass a graph path")
        state = repo / ".hx"
        if state != local:
            searched.append(str(state))
    if not state.is_dir():
        raise ValueError(f".hx directory missing or not a directory: {state} (searched: {', '.join(searched)}); "
                         f"run `hx extract ENTRY --root {shlex.quote(str(state.parent))}` or pass a graph path")

    graph = state / "graph.json"
    if os.path.lexists(graph):
        if graph.is_file():
            return str(graph)
        raise ValueError(f"{graph} is not a regular graph file; pass an existing graph path")
    graphs = state / "graphs"
    if graphs.is_dir():
        candidates = sorted(p for p in graphs.glob("*.json") if p.is_file())
        if candidates:
            return str(candidates[0])
    raise ValueError(f"no graph in {state} (expected graph.json or graphs/*.json); "
                     f"run `hx extract ENTRY --root {shlex.quote(str(state.parent))}` or "
                     f"`hx update --root {shlex.quote(str(state.parent))}`, or pass a graph path")
