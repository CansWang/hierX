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
    start = 2 if len(entry) > 2 and entry[1] == ":" and entry[2] in "/\\" else 0
    cut = entry.find(":", start)
    file, symbol = entry[:cut], entry[cut + 1:]
    if not file or not symbol:
        raise ValueError(f"entry must be <file>:<symbol>, got {entry!r}")
    return file, symbol


LANG_BY_EXT = {".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".C": "cpp",
               ".sv": "sv", ".svh": "sv", ".v": "sv", ".vh": "sv",
               ".rs": "rust", ".py": "python", ".pyi": "python", ".go": "go",
               ".sp": "spice", ".spi": "spice", ".spice": "spice", ".cir": "spice", ".ckt": "spice", ".net": "spice", ".sub": "spice",
               ".lib": "spice", ".inc": "spice"}
LANG_ALIASES = {"c++": "cpp", "verilog": "sv", "systemverilog": "sv", "rs": "rust", "py": "python", "sp": "spice", "netlist": "spice",
                "ngspice": "spice"}


def detect_lang(entry_file: str, lang: str = "auto") -> str:
    lang = LANG_ALIASES.get(lang, lang)
    if lang != "auto":
        return lang
    ext = os.path.splitext(entry_file)[1]
    if ext in LANG_BY_EXT:
        return LANG_BY_EXT[ext]
    raise FrontendError(f"cannot infer the language of {entry_file!r}; pass --lang c|cpp|sv|rust|python|go|spice")


def make_frontend(lang: str, root: str, *, compile_commands: Optional[str] = None, include_system: bool = False,
                  extra_args: Sequence[str] = (), resource_dir: Optional[str] = None, jobs: Optional[int] = None,
                  use_cache: bool = True, verbose: bool = False, sv_files: Sequence[str] = (), filelist: Optional[str] = None,
                  top: Optional[str] = None, verilator: str = "verilator", lsp_cmd: Optional[Sequence[str]] = None,
                  lsp_timeout: float = 90.0, dialect: str = "auto", deck: Optional[str] = None, search_paths: Sequence[str] = (),
                  deck_role: str = "deck"):
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
    if lang == "spice":
        from .frontends.spice_fe import SpiceFrontend
        fe = SpiceFrontend(root, deck=deck, dialect=dialect, search_paths=list(search_paths), use_cache=use_cache, verbose=verbose, deck_role=deck_role)
        fe.build_index()
        return fe, {}
    raise FrontendError(f"language {lang!r} is not supported (c, cpp, sv, rust, python, go, spice)")


def extract(entry: str, *, root: str = ".", compile_commands: Optional[str] = None,
            depth: Optional[int] = 3, type_depth: int = 2, include_callers: bool = False,
            include_system: bool = False, exclude: Sequence[str] = (), max_nodes: Optional[int] = None,
            extra_args: Sequence[str] = (), resource_dir: Optional[str] = None, jobs: Optional[int] = None,
            use_cache: bool = True, verbose: bool = False, lang: str = "auto",
            sv_files: Sequence[str] = (), filelist: Optional[str] = None, top: Optional[str] = None,
            verilator: str = "verilator", lsp_cmd: Optional[Sequence[str]] = None, lsp_timeout: float = 90.0,
            dialect: str = "auto", deck: Optional[str] = None, search_paths: Sequence[str] = ()) -> Graph:
    """Extract a bounded structure graph from one entry point.

    Args:
        entry: File and symbol separated by a colon, such as
            `src/main.c:app_run` or `ota.sp:.`.
        root: Project root; IDs are relative to its resolved path where possible.
        compile_commands: C/C++ compilation database file or containing directory.
        depth: Callee/child depth. Use None for unlimited traversal.
        type_depth: Nested field-type expansion depth; aliases do not consume a level.
        include_callers: Also traverse callers or parent instances above the entry.
        include_system: Expand definitions and types from system headers.
        exclude: Globs matched against definition paths to suppress expansion.
        max_nodes: Optional cap on expanded nodes; truncation is recorded in metadata.
        extra_args: Additional compiler/elaborator arguments, as separate tokens.
        resource_dir: Override Clang's resource-header directory.
        jobs: C/C++ parse-worker count; None selects the frontend default.
        use_cache: Read and write frontend caches when supported.
        verbose: Collect additional diagnostics; LSP traffic can write `.hx/lsp.log`.
        lang: Frontend name or auto to infer it from the entry file extension.
        sv_files: HDL source globs relative to root.
        filelist: Verilator argument file.
        top: HDL top module, inferred when possible.
        verilator: Verilator executable name or path.
        lsp_cmd: Language-server executable and arguments as a sequence, not shell text.
        lsp_timeout: Seconds allowed for language-server indexing/readiness.
        dialect: Netlist dialect: auto, spice, ngspice, or xyce.
        deck: Top deck supplying context for a netlist include/library entry.
        search_paths: Additional netlist include/library search directories.

    Returns:
        An in-memory graph with records, unresolved targets, statistics, replay
        arguments, and observed provenance. Use project.save_extraction for
        managed history, or its save method for a standalone file.

    Raises:
        ValueError: The entry has no valid file/symbol pair.
        FrontendError: A frontend cannot initialize or extract the requested entry.
            EntryNotFound is the lookup-specific subclass and carries suggestions.

    Notes:
        Extraction may create `.hx/cache` and launch external frontend processes.
        The frontend is closed after traversal. Partial results, including unresolved
        targets and netlist diagnostics, can be returned without an exception.
    """
    root = os.path.abspath(root)
    file, symbol = split_entry(entry)
    lang = detect_lang(file, lang)
    from . import provenance
    source = os.path.realpath(os.path.join(root, file))
    started = provenance.begin(source)
    if lang == "sv" and top is None and "." in symbol:
        top = symbol.split(".", 1)[0]   # instance path: its first segment is the top; otherwise verilator picks the top
    deck_arg, deck_role = deck, "deck"
    if lang == "spice" and deck is None:
        # The entry file is the deck unless --deck names the top deck (library/include entries). A `@name` entry
        # without --deck may be a standalone library: its line 1 is kept when it is a dot-directive (`auto`).
        deck = file
        deck_role = "auto" if symbol.startswith("@") else "deck"
    fe, extra_meta = make_frontend(lang, root, compile_commands=compile_commands, include_system=include_system,
                                   extra_args=extra_args, resource_dir=resource_dir, jobs=jobs, use_cache=use_cache,
                                   verbose=verbose, sv_files=sv_files, filelist=filelist, top=top, verilator=verilator,
                                   lsp_cmd=lsp_cmd, lsp_timeout=lsp_timeout, dialect=dialect, deck=deck, search_paths=search_paths,
                                   deck_role=deck_role)
    try:
        opts = TraverseOptions(depth=depth, type_depth=type_depth, include_callers=include_callers,
                               include_system=include_system, exclude=list(exclude), max_nodes=max_nodes)
        graph = extract_graph(fe, file, symbol, opts, root)
        graph.meta["entry_arg"] = entry
        graph.meta.update(extra_meta)
        graph.meta["extract_args"] = {
            "entry": entry, "root": root, "compile_commands": extra_meta.get("compile_commands"), "depth": depth, "type_depth": type_depth,
            "include_callers": include_callers, "include_system": include_system, "exclude": list(exclude),
            "max_nodes": max_nodes, "extra_args": list(extra_args), "resource_dir": resource_dir, "lang": lang,
            "sv_files": list(sv_files), "filelist": filelist, "top": top, "verilator": verilator,
            "lsp_cmd": list(lsp_cmd) if lsp_cmd else None, "lsp_timeout": lsp_timeout,
            "dialect": dialect, "deck": deck_arg if lang == "spice" else None, "search_paths": list(search_paths),   # as given: an omitted deck stays omitted on replay
        }
        graph.meta["index"] = fe.stats
        if getattr(fe, "errors", None):
            graph.meta["tu_errors"] = fe.errors
        if getattr(fe, "notes", None):
            graph.meta["notes"] = list(fe.notes)
        if verbose and getattr(fe, "diagnostics", None):
            graph.meta["diagnostics"] = fe.diagnostics[:200]
        try:
            inputs = provenance.observed_inputs(fe, root, source, graph.meta["extract_args"])
        except Exception as exc:  # best-effort metadata never prevents a usable graph
            inputs = {"coverage": "observed", "files": [], "sha256": provenance.digest([]),
                      "changed_during_extract": False, "diagnostics": [str(exc)]}
        provenance.finish(graph, started, inputs, source)
        return graph
    finally:
        close = getattr(fe, "close", None)
        if close:
            close()
