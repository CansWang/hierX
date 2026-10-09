"""Programmatic entry point: hx.api.extract(...) -> Graph. The CLI is a thin wrapper."""
from __future__ import annotations

import os
from typing import Optional, Sequence

from .model import Graph
from .traverse import TraverseOptions, extract_graph
from .frontends.base import FrontendError


def split_entry(entry: str) -> tuple[str, str]:
    """'src/main.c:app_run' -> ('src/main.c', 'app_run')."""
    if ":" not in entry:
        raise ValueError(f"entry must be <file>:<symbol>, got {entry!r}")
    file, symbol = entry.rsplit(":", 1)
    if not file or not symbol:
        raise ValueError(f"entry must be <file>:<symbol>, got {entry!r}")
    return file, symbol


def extract(entry: str, *, root: str = ".", compile_commands: Optional[str] = None,
            depth: Optional[int] = 3, type_depth: int = 2, include_callers: bool = False,
            include_system: bool = False, exclude: Sequence[str] = (), max_nodes: Optional[int] = None,
            extra_args: Sequence[str] = (), resource_dir: Optional[str] = None, jobs: Optional[int] = None,
            use_cache: bool = True, verbose: bool = False, lang: str = "auto") -> Graph:
    root = os.path.abspath(root)
    file, symbol = split_entry(entry)
    if lang not in ("auto", "c", "cpp", "c++"):
        raise FrontendError(f"language {lang!r} is not supported yet (Phase 1: C/C++ only)")
    from .frontends.clang_fe import ClangFrontend, find_compile_commands
    cc_dir = find_compile_commands(root, compile_commands)
    fe = ClangFrontend(root, cc_dir, extra_args=list(extra_args), include_system=include_system,
                       use_cache=use_cache, jobs=jobs, resource_dir=resource_dir, verbose=verbose)
    fe.build_index()
    opts = TraverseOptions(depth=depth, type_depth=type_depth, include_callers=include_callers,
                           include_system=include_system, exclude=list(exclude), max_nodes=max_nodes)
    graph = extract_graph(fe, file, symbol, opts, root)
    graph.meta["entry_arg"] = entry
    graph.meta["compile_commands"] = cc_dir
    graph.meta["extract_args"] = {
        "entry": entry, "root": root, "compile_commands": cc_dir, "depth": depth, "type_depth": type_depth,
        "include_callers": include_callers, "include_system": include_system, "exclude": list(exclude),
        "max_nodes": max_nodes, "extra_args": list(extra_args), "resource_dir": resource_dir, "lang": lang,
    }
    graph.meta["index"] = fe.stats
    if fe.errors:
        graph.meta["tu_errors"] = fe.errors
    if fe.notes:
        graph.meta["notes"] = list(fe.notes)
    if verbose and fe.diagnostics:
        graph.meta["diagnostics"] = fe.diagnostics[:200]
    return graph
