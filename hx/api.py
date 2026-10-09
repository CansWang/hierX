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


LANG_BY_EXT = {".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".C": "cpp",
               ".sv": "sv", ".svh": "sv", ".v": "sv", ".vh": "sv",
               ".rs": "rust", ".py": "python", ".pyi": "python", ".go": "go"}
LANG_ALIASES = {"c++": "cpp", "verilog": "sv", "systemverilog": "sv", "rs": "rust", "py": "python"}


def detect_lang(entry_file: str, lang: str = "auto") -> str:
    lang = LANG_ALIASES.get(lang, lang)
    if lang != "auto":
        return lang
    ext = os.path.splitext(entry_file)[1]
    if ext in LANG_BY_EXT:
        return LANG_BY_EXT[ext]
    raise FrontendError(f"cannot infer the language of {entry_file!r}; pass --lang c|cpp|sv|rust|python|go")


def make_frontend(lang: str, root: str, *, compile_commands: Optional[str] = None, include_system: bool = False,
                  extra_args: Sequence[str] = (), resource_dir: Optional[str] = None, jobs: Optional[int] = None,
                  use_cache: bool = True, verbose: bool = False, sv_files: Sequence[str] = (), filelist: Optional[str] = None,
                  top: Optional[str] = None, verilator: str = "verilator", lsp_cmd: Optional[Sequence[str]] = None,
                  lsp_timeout: float = 90.0):
    """Instantiate and index the frontend for `lang`. Returns (frontend, extra meta)."""
    if lang in ("c", "cpp"):
        from .frontends.clang_fe import ClangFrontend, find_compile_commands
        cc_dir = find_compile_commands(root, compile_commands)
        fe = ClangFrontend(root, cc_dir, extra_args=list(extra_args), include_system=include_system,
                           use_cache=use_cache, jobs=jobs, resource_dir=resource_dir, verbose=verbose)
        fe.build_index()
        return fe, {"compile_commands": cc_dir}
    if lang == "sv":
        from .frontends.verilator_fe import VerilatorFrontend
        fe = VerilatorFrontend(root, sv_files=list(sv_files), filelist=filelist, top=top, extra_args=list(extra_args),
                               use_cache=use_cache, verilator=verilator, verbose=verbose)
        fe.build_index()
        return fe, {}
    if lang in ("rust", "python", "go", "clangd"):
        from .frontends.lsp_fe import LspFrontend
        log = os.path.join(root, ".hx", "lsp.log") if verbose else None
        if log:
            os.makedirs(os.path.dirname(log), exist_ok=True)
        fe = LspFrontend(root, server=lang, cmd=list(lsp_cmd) if lsp_cmd else None, timeout=lsp_timeout, verbose=verbose, log_path=log)
        fe.build_index()
        return fe, {"server": " ".join(fe.cmd)}
    raise FrontendError(f"language {lang!r} is not supported (c, cpp, sv, rust, python, go)")


def extract(entry: str, *, root: str = ".", compile_commands: Optional[str] = None,
            depth: Optional[int] = 3, type_depth: int = 2, include_callers: bool = False,
            include_system: bool = False, exclude: Sequence[str] = (), max_nodes: Optional[int] = None,
            extra_args: Sequence[str] = (), resource_dir: Optional[str] = None, jobs: Optional[int] = None,
            use_cache: bool = True, verbose: bool = False, lang: str = "auto",
            sv_files: Sequence[str] = (), filelist: Optional[str] = None, top: Optional[str] = None,
            verilator: str = "verilator", lsp_cmd: Optional[Sequence[str]] = None, lsp_timeout: float = 90.0) -> Graph:
    root = os.path.abspath(root)
    file, symbol = split_entry(entry)
    lang = detect_lang(file, lang)
    if lang == "sv" and top is None and "." in symbol:
        top = symbol.split(".", 1)[0]   # instance path: its first segment is the top; otherwise verilator picks the top
    fe, extra_meta = make_frontend(lang, root, compile_commands=compile_commands, include_system=include_system,
                                   extra_args=extra_args, resource_dir=resource_dir, jobs=jobs, use_cache=use_cache,
                                   verbose=verbose, sv_files=sv_files, filelist=filelist, top=top, verilator=verilator,
                                   lsp_cmd=lsp_cmd, lsp_timeout=lsp_timeout)
    try:
        opts = TraverseOptions(depth=depth, type_depth=type_depth, include_callers=include_callers,
                               include_system=include_system, exclude=list(exclude), max_nodes=max_nodes)
        graph = extract_graph(fe, file, symbol, opts, root)
    finally:
        close = getattr(fe, "close", None)
        if close:
            close()
    graph.meta["entry_arg"] = entry
    graph.meta.update(extra_meta)
    graph.meta["extract_args"] = {
        "entry": entry, "root": root, "compile_commands": extra_meta.get("compile_commands"), "depth": depth, "type_depth": type_depth,
        "include_callers": include_callers, "include_system": include_system, "exclude": list(exclude),
        "max_nodes": max_nodes, "extra_args": list(extra_args), "resource_dir": resource_dir, "lang": lang,
        "sv_files": list(sv_files), "filelist": filelist, "top": top, "verilator": verilator,
        "lsp_cmd": list(lsp_cmd) if lsp_cmd else None, "lsp_timeout": lsp_timeout,
    }
    graph.meta["index"] = fe.stats
    if getattr(fe, "errors", None):
        graph.meta["tu_errors"] = fe.errors
    if getattr(fe, "notes", None):
        graph.meta["notes"] = list(fe.notes)
    if verbose and getattr(fe, "diagnostics", None):
        graph.meta["diagnostics"] = fe.diagnostics[:200]
    return graph
