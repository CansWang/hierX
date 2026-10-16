"""DesignIndex: every file of a deck's include closure (selected library sections only), declarations keyed by
(declaring scope, folded name) with their guards, globals, the deck's top-level items, directives, control blocks,
probes (every candidate path tried, missing ones included) and diagnostics. Declarations are indexed for the whole
closure before any instance is resolved, so forward references work."""
from __future__ import annotations

import itertools
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from .. import ids as _ids
from ..cache import TUCache
from .lexer import RawStatement
from .names import (EMPTY_GUARD, Guard, chain_id, decl_identity, fold, guard_compatible, guard_id, guard_sorted, guard_union)
from .parser import (Conditional, ControlBlock, Directive, Element, Encrypted, EndStmt, FileSummary, GlobalStmt, Include,
                     LibRef, LibSection, ModelStmt, ParamStmt, RawFile, Stmt, SubcktDef, Title, Unparsed, lex_file, structure)
from .profiles import Profile
from .hashing import scope_hash

SUMMARY_VERSION = 1


@dataclass
class Decl:
    kind: str                              # subckt | model | param
    scope: tuple                           # declaring scope (tuple of folded definition names)
    name: str                              # folded
    spelled: str
    guard: Guard
    file: str
    line: int
    end_line: int
    stmt: object = None
    ports: list[str] = field(default_factory=list)                 # subckt
    params: list[tuple[str, str]] = field(default_factory=list)    # subckt defaults
    items: list[tuple[Stmt, Guard]] = field(default_factory=list)  # subckt body, flattened, guards relative to the body
    type: str = ""                         # model
    params_text: str = ""                  # model
    expr: str = ""                         # param
    section: Optional[str] = None
    bins: list["Decl"] = field(default_factory=list)              # a bin family record (model)

    @property
    def gid(self) -> str:
        return guard_id(self.guard)

    @property
    def identity(self) -> str:
        return decl_identity(self.scope, self.name, self.gid)

    @property
    def body_scope(self) -> tuple:
        return self.scope + (self.name,)


@dataclass
class Lookup:
    alternatives: list[Decl]
    ambiguous: bool = False
    bins: list[Decl] = field(default_factory=list)
    scope_found: Optional[tuple] = None

    @property
    def found(self) -> bool:
        return bool(self.alternatives) or bool(self.bins)


@dataclass
class FileRecord:
    path: str
    role: str
    section: Optional[str]
    from_file: Optional[str]
    from_line: Optional[int]
    resolved_by: str
    outside_root: bool


class DesignIndex:
    def __init__(self, deck: str, profile: Profile, dialect: str, search_paths: list[str], root: str,
                 cache: Optional[TUCache] = None, deck_role: str = "deck"):
        self.deck = _ids.realpath(deck)
        self.deck_role = deck_role                    # deck (line 1 is the title) | library (line 1 kept: a standalone `@name` entry)
        self.profile = profile
        self.dialect = dialect
        self.root = _ids.realpath(root)
        self.search_paths = [p if os.path.isabs(p) else os.path.join(self.root, p) for p in search_paths]
        self.cache = cache
        self.files: list[FileRecord] = []
        self.decls: dict[tuple, list[Decl]] = {}
        self.globals: dict[str, str] = {}
        self.top_items: list[tuple[Stmt, Guard]] = []
        self.directives: list[dict] = []
        self.control_blocks: list[dict] = []
        self.diagnostics: list[dict] = []
        self.deps: dict[str, int] = {}
        self.probes: list[dict] = []
        self.resolution: dict[tuple[str, int], Optional[str]] = {}   # (including file, line) -> resolved path
        self.title: str = ""
        self.stats: dict = {"files": 0, "parsed": 0, "cached": 0, "sections": []}
        self._loaded: dict[tuple[str, str], FileSummary] = {}

    # ------------------------------------------------------------ files
    def _diag(self, code: str, message: str, file: Optional[str], line: Optional[int], severity: str = "error",
              scope: tuple = (), node: Optional[str] = None) -> None:
        self.diagnostics.append({"severity": severity, "code": code, "message": message, "file": file, "line": line,
                                 "node": node, "scope": "/".join(scope)})

    def _rel(self, path: Optional[str]) -> str:
        return _ids.rel(path, self.root) if path else "?"

    @property
    def root_role(self) -> str:
        """The role the root file is loaded under: a library root reads like an include (line 1 kept, diagnostics reported)."""
        return "deck" if self.deck_role == "deck" else "include"

    def resolve_path(self, text: str, from_file: str, what: str, from_line: Optional[int]) -> Optional[str]:
        """Absolute path → including file's directory → each --search-path → root. Every candidate is probed and
        recorded, missing ones included, so the watcher and the cache can react when one appears."""
        text = os.path.expanduser(text)
        cands: list[str] = []
        if os.path.isabs(text):
            cands.append(text)
        else:
            cands.append(os.path.join(os.path.dirname(from_file), text))
            cands += [os.path.join(sp, text) for sp in self.search_paths]
            cands.append(os.path.join(self.root, text))
        seen: list[str] = []
        probe = {"what": what, "requested": text, "from": {"file": self._rel(from_file), "line": from_line},
                 "candidates": [], "resolved": None}
        resolved = None
        for c in cands:
            c = os.path.normpath(c)
            if c in seen:
                continue
            seen.append(c)
            exists = os.path.isfile(c)
            probe["candidates"].append({"path": c, "exists": exists})
            if exists and resolved is None:
                resolved = _ids.realpath(c)
                probe["resolved"] = resolved
                break
        self.probes.append(probe)
        return resolved

    def load(self, path: str, role: str) -> FileSummary:
        key = (path, role)
        if key in self._loaded:
            return self._loaded[key]
        raw: Optional[RawFile] = None
        extra = (SUMMARY_VERSION, self.root)
        if self.cache is not None:
            summary = self.cache.load(path, [self.dialect], extra)
            if summary is not None:
                raw = RawFile.from_json(summary["raw"])
                self.stats["cached"] += 1
        if raw is None:
            raw = lex_file(path, self.profile)
            self.stats["parsed"] += 1
            if self.cache is not None:
                self.cache.store(path, [self.dialect], {"raw": raw.to_json(), "deps": TUCache.snapshot_deps([path])}, extra)
        try:
            self.deps[path] = os.stat(path).st_mtime_ns
        except OSError:
            pass
        fs = structure(raw, role, self.profile)
        if role != "library":                       # a library's diagnostics count per selected section (see _lib_diagnostics)
            for d in fs.diagnostics:
                self._file_diag(d)
        self._loaded[key] = fs
        return fs

    def _file_diag(self, d: dict) -> None:
        self.diagnostics.append({"severity": d["severity"], "code": d["code"], "message": d["message"],
                                 "file": d["file"], "line": d["line"], "node": None, "scope": ""})

    def _lib_diagnostics(self, lib, sec: LibSection) -> None:
        """Only the sections a `.lib file section` reference selects are read by the simulator, so only their
        statement diagnostics are reported (the GF180 library's unselected `bjt_*` sections stay silent)."""
        seen = self.__dict__.setdefault("_lib_diag_seen", set())
        end = sec.span_end
        for d in lib.diagnostics:
            key = (d["file"], d["line"], d["code"])
            if sec.line <= d["line"] <= end and key not in seen:
                seen.add(key)
                self._file_diag(d)

    # ------------------------------------------------------------ build
    def build(self) -> "DesignIndex":
        t0 = time.time()
        if not os.path.isfile(self.deck):
            from ..frontends.base import FrontendError
            raise FrontendError(f"deck {self._rel(self.deck)} does not exist")
        self.files.append(FileRecord(self.deck, self.deck_role, None, None, None, "entry", not self.deck.startswith(self.root + os.sep)))
        fs = self.load(self.deck, self.root_role)
        self.title = fs.title or ""
        self._expand(fs.statements, (), EMPTY_GUARD, self.deck, self.top_items, [self.deck], None, EMPTY_GUARD)
        self.stats["files"] = len(self.files)
        self.stats["index_seconds"] = round(time.time() - t0, 3)
        return self

    def _register(self, d: Decl) -> None:
        self.decls.setdefault((d.kind, d.scope, d.name), []).append(d)

    def _expand(self, stmts: list[Stmt], scope: tuple, guard: Guard, file: str, items: list, stack: list[str],
                section: Optional[str], defn_guard: Guard) -> None:
        """Flatten `stmts` into `items` (elements, declarations, directives with their guards relative to this body);
        declarations register under `scope` with guard = defn_guard ∪ guard (visible only to occurrences of the
        alternative that holds them). Includes and selected library sections expand in place."""
        cs = self.profile.case_sensitive
        for st in stmts:
            if isinstance(st, Title):
                continue
            if isinstance(st, SubcktDef):
                d = Decl(kind="subckt", scope=scope, name=fold(st.name, cs), spelled=st.name, guard=guard_union(defn_guard, guard),
                         file=st.file, line=st.line, end_line=st.end_raw.end_line if st.end_raw else st.end_line, stmt=st,
                         ports=list(st.ports), params=list(st.params), section=section)
                self._register(d)
                items.append((st, guard))
                self._expand(st.body, d.body_scope, EMPTY_GUARD, file, d.items, stack, section, d.guard)
                continue
            if isinstance(st, Include):
                path = self.resolve_path(st.path_text, file, "include", st.line)
                self.resolution[(file, st.line)] = path
                if path is None:
                    self._diag("missing-include", f".include {st.path_text!r} not found (from {self._rel(file)}:{st.line})", file, st.line, scope=scope)
                    items.append((st, guard))
                    continue
                if path in stack:
                    self._diag("include-cycle", f".include {st.path_text!r} is already being read ({' -> '.join(self._rel(p.split('::')[0]) for p in stack)})", file, st.line, scope=scope)
                    continue
                self.files.append(FileRecord(path, "include", section, self._rel(file), st.line, "search" if not os.path.isabs(st.path_text) else "absolute",
                                             not path.startswith(self.root + os.sep)))
                inc = self.load(path, "include")
                items.append((st, guard))
                self._expand(inc.statements, scope, guard, path, items, stack + [path], section, defn_guard)
                continue
            if isinstance(st, LibRef):
                path = self.resolve_path(st.path_text, file, "lib", st.line)
                self.resolution[(file, st.line)] = path
                if path is None:
                    self._diag("missing-include", f".lib {st.path_text!r} not found (from {self._rel(file)}:{st.line})", file, st.line, scope=scope)
                    items.append((st, guard))
                    continue
                want = fold(st.section, cs)
                lib_key = f"{path}::{want}"                    # a section may pull sibling sections of its own file (GF180 sm141064)
                if lib_key in stack:
                    self._diag("include-cycle", f".lib {st.path_text!r} section {st.section!r} is already being read", file, st.line, scope=scope)
                    continue
                lib = self.load(path, "library")
                sections = [x for x in lib.statements if isinstance(x, LibSection) and fold(x.name, cs) == want]
                self.files.append(FileRecord(path, "lib", st.section, self._rel(file), st.line, "search" if not os.path.isabs(st.path_text) else "absolute",
                                             not path.startswith(self.root + os.sep)))
                if not sections:
                    self._diag("missing-lib-section", f"section {st.section!r} not found in {self._rel(path)}", file, st.line, scope=scope)
                    items.append((st, guard))
                    continue
                self.stats["sections"].append([self._rel(path), st.section])
                items.append((st, guard))
                for sec in sections:
                    self._lib_diagnostics(lib, sec)
                    self._expand(sec.body, scope, guard, path, items, stack + [lib_key], st.section, defn_guard)
                continue
            if isinstance(st, LibSection):
                self._diag("lib-section-skipped", f".lib {st.name} … .endl read outside a .lib reference is not selected", file, st.line, "info", scope=scope)
                continue
            if isinstance(st, Conditional):
                cid = chain_id(scope, [c for c, _ in st.branches if c], cs)
                for i, (_cond, body) in enumerate(st.branches):
                    self._expand(body, scope, guard_union(guard, frozenset({(cid, i)})), file, items, stack, section, defn_guard)
                continue
            if isinstance(st, ParamStmt):
                for name, expr in st.assignments:
                    self._register(Decl(kind="param", scope=scope, name=fold(name, cs), spelled=name, guard=guard_union(defn_guard, guard),
                                        file=st.file, line=st.line, end_line=st.end_line, stmt=st, expr=expr, section=section))
                items.append((st, guard))
                continue
            if isinstance(st, ModelStmt):
                self._register(Decl(kind="model", scope=scope, name=fold(st.name, cs), spelled=st.name, guard=guard_union(defn_guard, guard),
                                    file=st.file, line=st.line, end_line=st.end_line, stmt=st, type=st.type, params_text=st.params_text, section=section))
                items.append((st, guard))
                continue
            if isinstance(st, GlobalStmt):
                for n in st.names:
                    self.globals.setdefault(fold(n, cs), n)
                items.append((st, guard))
                continue
            if isinstance(st, ControlBlock):
                self.control_blocks.append({"file": self._rel(file), "line": st.line, "end_line": st.end_line, "text": st.text, "scope": "/".join(scope)})
                continue
            if isinstance(st, Encrypted):
                items.append((st, guard))
                continue
            if isinstance(st, Unparsed):
                items.append((st, guard))
                continue
            if isinstance(st, (Directive, EndStmt)):
                self.directives.append({"name": getattr(st, "name", ".end"), "role": getattr(st, "role", "end"), "text": st.text,
                                        "file": self._rel(file), "line": st.line, "end_line": st.end_line, "scope": "/".join(scope),
                                        "guard": guard_id(guard)})
                items.append((st, guard))
                continue
            if isinstance(st, Element):
                items.append((st, guard))
                continue
            items.append((st, guard))

    # ------------------------------------------------------------ lookup
    def lookup(self, kind: str, scope: tuple, name: str, guard: Guard) -> Lookup:
        """Guard-aware lexical lookup: innermost scope outward, stopping at the first scope with a visible
        declaration. Visible = guard compatible with the requester's. Mutually exclusive visible declarations are
        alternatives; compatible ones (same or independent guards) are ambiguous. Models fall back to a bin family
        (`name.<digits>`)."""
        folded = fold(name, self.profile.case_sensitive)
        chain = [scope[:i] for i in range(len(scope), -1, -1)]
        for s in chain:
            entries = self.decls.get((kind, s, folded))
            if not entries:
                continue
            visible = [d for d in entries if guard_compatible(d.guard, guard)]
            if not visible:
                continue
            ambiguous = any(guard_compatible(a.guard, b.guard) for a, b in itertools.combinations(visible, 2))
            return Lookup(alternatives=visible, ambiguous=ambiguous, scope_found=s)
        if kind == "model":
            for s in chain:
                bins = []
                for (k, sc, nm), entries in self.decls.items():
                    if k == "model" and sc == s and nm.startswith(folded + ".") and nm[len(folded) + 1:].isdigit():
                        bins += [d for d in entries if guard_compatible(d.guard, guard)]
                if bins:
                    bins.sort(key=lambda d: (int(d.name.rsplit(".", 1)[1]), d.line))
                    return Lookup(alternatives=[], ambiguous=False, bins=bins, scope_found=s)
        return Lookup(alternatives=[])

    def is_model_visible(self, scope: tuple, name: str, guard: Guard) -> bool:
        return self.lookup("model", scope, name, guard).found

    def shadowed(self, kind: str, scope: tuple, name: str) -> list[Decl]:
        """Outer declarations hidden by an inner one of the same name (informational)."""
        folded = fold(name, self.profile.case_sensitive)
        out = []
        for i in range(len(scope) - 1, -1, -1):
            out += self.decls.get((kind, scope[:i], folded), [])
        return out

    # ------------------------------------------------------------ hashing
    def item_texts(self, items: list[tuple[Stmt, Guard]]) -> list[tuple[str, str]]:
        """`(guard key, text)` per item: the guard key is the sorted `chain#branch` list (chains carry canonical
        conditions, so spacing never matters), empty for an unconditional statement."""
        out = []
        for st, g in items:
            key = "|".join(f"{c}#{i}" for c, i in guard_sorted(g)) if g else ""
            if isinstance(st, SubcktDef):
                out.append((key, st.text + " :: " + self.scope_hash_of(self._decl_for(st))))
            else:
                out.append((key, st.text))
        return out

    def _decl_for(self, st: SubcktDef) -> Optional[Decl]:
        for entries in self.decls.values():
            for d in entries:
                if d.stmt is st:
                    return d
        return None

    def scope_hash_of(self, d: Optional[Decl]) -> str:
        if d is None:
            return "sha1:" + "0" * 40
        cache = self.__dict__.setdefault("_sh", {})
        key = id(d)
        if key not in cache:
            # The header (ports, defaults) is part of the definition: a port-order edit changes its hash.
            head = [("", d.stmt.text)] if getattr(d.stmt, "text", None) else []
            cache[key] = scope_hash(head + self.item_texts(d.items), self.profile)
        return cache[key]

    def top_hash(self) -> str:
        return scope_hash(self.item_texts(self.top_items), self.profile)

    def all_decls(self, kind: Optional[str] = None):
        for (k, _s, _n), entries in self.decls.items():
            if kind is None or k == kind:
                for d in entries:
                    yield d
