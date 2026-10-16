"""SPICE-family netlist frontend (Phase N1): deck → subcircuit instances → devices as nodes, hierarchy as `instance`
edges, controlling references as `ref` edges, electrical connectivity in the additive `circuit` block attached by
`finalize()`. Native parser (hx/netlist/*); no simulator is needed. Ids: occurrence ids carry the owning root
(`sp:<deck>::xdut.m1`, `sp:<lib>::@opamp.m1`); guarded occurrences append `#<guard_id>`."""
from __future__ import annotations

import difflib
import os
import time
from typing import Optional

from .. import ids as _ids
from ..cache import TUCache
from ..model import GlobalRefs, GlobalVar, Loc, Node, Param
from ..netlist.hashing import statement_hash
from ..netlist.index import Decl, DesignIndex, Lookup
from ..netlist.names import decl_identity, fold, guard_json, guard_text, path_str, split_path
from ..netlist.profiles import get_profile
from ..netlist.resolve import Elaborator, Occurrence
from .base import CallSite, DeclRecord, EntryNotFound, Frontend, FrontendError, FunctionRecord, TypeRecord

SUMMARY_VERSION = 1


def _squash(text: str, limit: int = 200) -> str:
    s = " ".join(text.split())
    return s if len(s) <= limit else s[:limit - 1] + "…"


class SpiceFrontend(Frontend):
    lang = "sp"

    def __init__(self, root: str, *, deck: Optional[str] = None, dialect: str = "auto", search_paths=(), use_cache: bool = True,
                 cache_dir: Optional[str] = None, verbose: bool = False, deck_role: str = "deck"):
        self.root = _ids.realpath(root)
        self.deck_arg = deck
        self.dialect_arg = dialect
        self.deck_role_arg = deck_role                     # deck | library | auto (auto: a dot-directive on line 1 means library)
        self.deck_role = "deck" if deck_role == "auto" else deck_role
        self.search_paths = list(search_paths)
        self.cache = TUCache(cache_dir or os.path.join(self.root, ".hx", "cache"), enabled=use_cache)
        self.verbose = verbose
        self.stats: dict = {}
        self.notes: list[str] = []
        self.errors: list[dict] = []
        self.diagnostics: list[dict] = []
        self.deps: list[str] = []
        self.probes: list[dict] = []
        self.index: Optional[DesignIndex] = None
        self.profile = None
        self.dialect = dialect
        self._elabs: dict[str, Elaborator] = {}          # root tag -> elaborator
        self._occ: dict[str, tuple[str, Occurrence]] = {}  # frontend key -> (root tag, occurrence)
        self._by_id: dict[str, str] = {}                   # node id -> frontend key
        self._missing: dict[str, dict] = {}                # synthetic keys for missing reference targets

    def provenance_inputs(self) -> dict[str, Optional[int]]:
        deps = dict(self.index.deps) if self.index else {}
        for probe in self.probes:
            for candidate in probe.get("candidates", []):
                path = candidate.get("path")
                if path and path not in deps:
                    if not candidate.get("exists"):
                        deps[path] = None
                        continue
                    try:
                        deps[path] = os.stat(path).st_mtime_ns
                    except FileNotFoundError:
                        deps[path] = None
        return deps

    # ------------------------------------------------------------ index
    def _abs(self, file: str) -> str:
        return _ids.realpath(file if os.path.isabs(file) else os.path.join(self.root, file))

    def _rel(self, path: Optional[str]) -> str:
        return _ids.rel(path, self.root) if path else "?"

    def build_index(self) -> None:
        t0 = time.time()
        deck = self._abs(self.deck_arg) if self.deck_arg else None
        if deck is None:
            raise FrontendError("a netlist frontend needs the deck file (the entry file, or --deck FILE)")
        if not os.path.isfile(deck):
            raise FrontendError(f"deck {self._rel(deck)} does not exist")
        with open(deck, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        self.profile = get_profile(self.dialect_arg, text)
        self.dialect = self.profile.name
        if self.deck_role_arg == "auto":
            # A standalone library (`lib.sp:@name` without --deck) keeps its line 1: a deck's first line is a title
            # whatever it says, a library's is usually `.subckt`, `.lib`, `.param` or `.model`.
            first = text.split("\n", 1)[0].strip()
            self.deck_role = "library" if first.startswith(".") else "deck"
        self.index = DesignIndex(deck, self.profile, self.dialect, self.search_paths, self.root, self.cache, deck_role=self.deck_role).build()
        self._elabs["deck"] = Elaborator(self.index, "deck")
        self.deps = sorted(self.index.deps)
        self.probes = list(self.index.probes)
        self._refresh_diagnostics()
        self.stats = {"tus": self.index.stats["files"], "files": self.index.stats["files"], "parsed": self.index.stats["parsed"],
                      "cached": self.index.stats["cached"], "tu_errors": 0, "warnings": 0, "dialect": self.dialect,
                      "deck": self._rel(deck), "deck_role": self.deck_role, "search_paths": list(self.search_paths), "sections": self.index.stats["sections"],
                      "definitions": sum(1 for _ in self.index.all_decls("subckt")),
                      "models": sum(1 for _ in self.index.all_decls("model")), "deps": [self._rel(p) for p in self.deps],
                      "diagnostics": 0, "errors": 0, "index_seconds": round(time.time() - t0, 3)}
        self._count_diags()

    def _refresh_diagnostics(self) -> None:
        self.diagnostics = list(self.index.diagnostics) + [d for e in self._elabs.values() for d in e.diagnostics]

    def _count_diags(self) -> None:
        self._refresh_diagnostics()
        by_code: dict[str, int] = {}
        for d in self.diagnostics:
            by_code[d["code"]] = by_code.get(d["code"], 0) + 1
        self.stats["diagnostics"] = len(self.diagnostics)
        self.stats["errors"] = sum(1 for d in self.diagnostics if d["severity"] == "error")
        self.stats["diagnostics_by_code"] = dict(sorted(by_code.items(), key=lambda kv: -kv[1]))
        self.notes = [n for n in self.notes if not n.startswith("netlist:")]
        if self.diagnostics:
            top = ", ".join(f"{c} {n}" for c, n in list(self.stats["diagnostics_by_code"].items())[:5])
            self.notes.append(f"netlist: {len(self.diagnostics)} diagnostic(s) ({top}); see circuit.diagnostics" + ("" if self.verbose else " and --verbose for the first ones"))

    # ------------------------------------------------------------ roots and keys
    def _root_tag_for_decl(self, d: Decl) -> str:
        return "@" + decl_identity(d.scope, d.name, d.gid).lstrip("/")

    def _elab_for(self, tag: str) -> Elaborator:
        return self._elabs[tag]

    def _ensure_def_root(self, d: Decl) -> str:
        tag = self._root_tag_for_decl(d)
        if tag not in self._elabs:
            self._elabs[tag] = Elaborator(self.index, "subckt", d)
        return tag

    def _key(self, tag: str, occ: Occurrence) -> str:
        k = f"{tag}/{occ.key}"
        if k not in self._occ:
            self._occ[k] = (tag, occ)
            self._by_id[self._id_of(tag, occ)] = k
        return k

    def _root_file(self, tag: str) -> str:
        if tag == "deck":
            return self.index.deck
        d = self._elabs[tag].root.decl
        return d.file

    def _root_qual(self, tag: str) -> str:
        if tag == "deck":
            return f"(deck) {os.path.basename(self.index.deck)}"
        return tag

    def _id_of(self, tag: str, occ: Occurrence) -> str:
        qual = self._root_qual(tag)
        if occ.kind != "root":
            tail = path_str(occ.path) + occ.suffix
            qual = tail if tag == "deck" else f"{qual}.{tail}"
        return _ids.node_id("sp", self._rel(self._root_file(tag)), qual)

    # ------------------------------------------------------------ entry
    def _find_definitions(self, name: str) -> list[Decl]:
        """`@name` or `@scope/name` → matching subckt declarations (all guards)."""
        parts = [p for p in name.split("/") if p]
        if not parts:
            return []
        cs = self.profile.case_sensitive
        want_scope, want_name = tuple(fold(p, cs) for p in parts[:-1]), fold(parts[-1], cs)
        out = []
        for d in self.index.all_decls("subckt"):
            if d.name == want_name and (not want_scope or d.scope == want_scope):
                out.append(d)
        if not want_scope and any(d.scope == () for d in out):
            out = [d for d in out if d.scope == ()]          # a bare name means the top-level definition; `@scope/name` reaches a nested one
        return out

    def _walk_path(self, tag: str, segments: list[str]) -> Optional[Occurrence]:
        elab = self._elabs[tag]
        cur = elab.root
        cs = self.profile.case_sensitive
        for seg in segments:
            name, _, rest = seg.partition("#")
            gid, _, dup = rest.partition("~")
            if "~" in name and not rest:
                name, _, dup = name.partition("~")
            f = fold(name, cs)
            cands = [c for c in elab.children(cur) if c.path[-1] == f]
            if gid:
                cands = [c for c in cands if c.gid == gid]
            if dup:
                cands = [c for c in cands if c.dup_suffix == "~" + dup]
            if not cands:
                return None
            if len(cands) > 1:
                raise EntryNotFound(f"'{seg}' names {len(cands)} occurrences; pick one by its suffix",
                                    [path_str(c.path) + c.suffix for c in cands][:8])
            cur = cands[0]
        return cur

    def locate_entry(self, file: str, symbol: str) -> str:
        abs_file = self._abs(file)
        rel_file = self._rel(abs_file)
        deck = self.index.deck
        if symbol == ".":
            if abs_file != deck:
                raise EntryNotFound(f"'.' is the whole deck, which is {self._rel(deck)}, not {rel_file}", [f"{self._rel(deck)}:."])
            return self._key("deck", self._elabs["deck"].root)
        if symbol.startswith("@"):
            return self._definition_entry(abs_file, symbol[1:])
        forced = symbol.startswith("/")
        path = symbol[1:] if forced else symbol
        segs = split_path(path)
        occ = self._walk_path("deck", segs)
        defs = [] if forced else self._find_definitions(path)
        if occ is not None and defs:
            raise EntryNotFound(f"'{symbol}' is both an instance path and a subcircuit definition; use '@{symbol}' for the definition or '/{symbol}' for the instance",
                                [f"@{symbol}", f"/{symbol}"])
        if occ is not None:
            self._check_entry_file(abs_file, "deck", occ)
            return self._key("deck", occ)
        if defs:
            return self._definition_entry(abs_file, path)
        names = [d.spelled for d in self.index.all_decls("subckt")]
        paths = self._enumerate_paths("deck", 3, 5000)
        sugg = difflib.get_close_matches(path, names + paths, n=6, cutoff=0.5)
        raise EntryNotFound(f"'{symbol}' is neither an instance path of {self._rel(deck)} nor a subcircuit definition "
                            f"(use '.' for the whole deck, 'x1.m2' for an occurrence, '@name' for a definition)", sugg)

    def _definition_entry(self, abs_file: str, name: str) -> str:
        defs = self._find_definitions(name)
        if not defs:
            names = [d.spelled for d in self.index.all_decls("subckt")]
            raise EntryNotFound(f"no subcircuit definition '{name}' in the deck's include closure", difflib.get_close_matches(name.split('/')[-1], names, n=6, cutoff=0.5))
        in_file = [d for d in defs if _ids.realpath(d.file) == abs_file]
        if not in_file:
            files = sorted({self._rel(d.file) for d in defs})
            raise EntryNotFound(f"'{name}' is defined in {', '.join(files)}, not in {self._rel(abs_file)}", [f"{f}:@{name}" for f in files])
        if len(in_file) > 1:
            raise EntryNotFound(f"'{name}' has {len(in_file)} declarations in {self._rel(abs_file)} (guarded alternatives or duplicates); name the scope with '@scope/name'",
                                [f"@{d.identity.lstrip('/')}" for d in in_file])
        tag = self._ensure_def_root(in_file[0])
        return self._key(tag, self._elabs[tag].root)

    def _check_entry_file(self, abs_file: str, tag: str, occ: Occurrence) -> None:
        ok: set[str] = {self._root_file(tag)}
        p = occ
        while p is not None and p.kind != "root":
            if p.element is not None:
                ok.add(_ids.realpath(p.element.file))
            if p.decl is not None:
                ok.add(_ids.realpath(p.decl.file))
            p = p.parent
        if abs_file not in ok:
            raise EntryNotFound(f"{self._rel(abs_file)} holds nothing on the path '{path_str(occ.path)}'; use one of: " + ", ".join(sorted(self._rel(f) for f in ok)),
                                [f"{self._rel(f)}:{path_str(occ.path)}" for f in sorted(ok)])

    def _enumerate_paths(self, tag: str, depth: int, cap: int) -> list[str]:
        elab = self._elabs[tag]
        out: list[str] = []
        stack = [(elab.root, 0)]
        while stack and len(out) < cap:
            occ, d = stack.pop()
            for c in elab.children(occ):
                out.append(path_str(c.path) + c.suffix)
                if c.kind == "inst" and d + 1 < depth:
                    stack.append((c, d + 1))
        return out

    def instances_of(self, matches, tag: str = "deck", cap: int = 100000) -> list[Occurrence]:
        """Every instance occurrence under the root `tag` whose definition satisfies `matches(decl)` (guarded ones
        included), breadth first; recursive and too-deep occurrences are not descended into."""
        elab = self._elabs[tag]
        out: list[Occurrence] = []
        queue = [elab.root]
        while queue and len(out) < cap:
            occ = queue.pop(0)
            for c in elab.children(occ):
                if c.kind != "inst":
                    continue
                if c.decl is not None and matches(c.decl):
                    out.append(c)
                if not c.recursive and not c.too_deep:
                    queue.append(c)
        return out

    # ------------------------------------------------------------ records
    def stable_id(self, key: str) -> Optional[str]:
        if key in self._missing:
            return self._missing[key]["id"]
        if key not in self._occ:
            return None
        tag, occ = self._occ[key]
        return self._id_of(tag, occ)

    def _loc_of(self, occ: Occurrence, tag: str) -> Loc:
        if occ.kind == "root":
            if occ.decl is not None:
                return Loc(file=self._rel(occ.decl.file), line=occ.decl.line, end_line=occ.decl.end_line)
            n = self.index.load(self.index.deck, self.index.root_role).statements
            last = n[-1].end_line if n else 1
            return Loc(file=self._rel(self.index.deck), line=1, end_line=last)
        el = occ.element
        return Loc(file=self._rel(el.file), line=el.line, end_line=el.end_line)

    def _global_keys(self, elab: Elaborator, net_keys: list[str]) -> list[str]:
        return [f"net:{k}" for k in net_keys if k in self.index.globals]

    def function(self, key: str) -> Optional[FunctionRecord]:
        if key not in self._occ:
            return None
        tag, occ = self._occ[key]
        elab = self._elabs[tag]
        nid = self._id_of(tag, occ)
        loc = self._loc_of(occ, tag)
        callsites: list[CallSite] = []
        global_keys: list[str] = []
        if occ.kind == "dev":
            rec = elab.device(occ)
            fam = rec.family
            params = [Param(name=t["terminal"], type="terminal", dir="inout", dir_source="explicit") for t in rec.terminals]
            attrs = {"family": fam.letter if fam else "?", "element": fam.element if fam else "?",
                     "model": rec.parts.master if fam and fam.model != "none" else None, "model_refs": list(rec.model_refs),
                     "model_status": rec.model_status, "parameters": dict(rec.parts.params), "value": rec.parts.value,
                     "scope": path_str(occ.parent.path) if occ.parent else "", "guard": guard_text(occ.guard) or None,
                     "guard_id": occ.gid or None, "controls": [], "tokens": None if fam else _squash(occ.element.text)}
            for r in rec.refs:
                # every guard-compatible target is an alternative (one `ref` edge each); a missing one is a ghost
                tkeys = [self._key(tag, t) for t in r["targets"]] or [self._missing_key(tag, occ, r)]
                attrs["controls"].append({"role": r["role"], "as_written": r["as_written"], "targets": [self.stable_id(k) for k in tkeys]})
                for k in tkeys:
                    callsites.append(CallSite(callee_key=k, name=r["as_written"], loc=loc, kind="ref", args=[]))
            global_keys = self._global_keys(elab, [t["net"] for t in rec.terminals])
            node = Node(id=nid, kind="device", name=occ.name, qualname=path_str(occ.path) + occ.suffix, lang="sp",
                        loc=loc, signature=_squash(occ.element.text), storage=None, body_hash=statement_hash(occ.element.text, self.profile),
                        precision="syntax", returns=None, params=params, globals=GlobalRefs(reads=[self._global_id(k) for k in global_keys]),
                        attrs=attrs)
            return FunctionRecord(node=node, callsites=callsites, type_keys=[], global_keys=global_keys)
        if occ.kind == "inst":
            rec = elab.instance(occ)
            d = occ.decl
            ports = d.ports if d else []
            sig = f"{d.spelled if d else (rec.parts.master or '?')} {occ.name} ({' '.join(rec.parts.positional)})"
            params = [Param(name=p, type="port", dir="inout", dir_source="heuristic") for p in ports]
            attrs = {"definition": d.spelled if d else rec.parts.master, "definition_refs": [{"guard_id": d.gid, "key": d.identity}] if d else [],
                     "definition_file": self._rel(d.file) if d else None, "parameters": dict(rec.parts.params),
                     "defaults": dict(d.params) if d else {}, "scope": path_str(occ.parent.path) if occ.parent else "",
                     "guard": guard_text(occ.guard) or None, "guard_id": occ.gid or None}
            node = Node(id=nid, kind="instance", name=occ.name, qualname=path_str(occ.path) + occ.suffix, lang="sp",
                        loc=loc, signature=sig, storage=None, body_hash=self.index.scope_hash_of(d) if d else statement_hash(occ.element.text, self.profile),
                        precision="syntax", returns=None, params=params, globals=GlobalRefs(), attrs=attrs)
            global_keys = self._global_keys(elab, [b["outer"] for b in rec.bindings])
            node.globals.reads = [self._global_id(k) for k in global_keys]
            for c in elab.children(occ):
                callsites.append(self._child_callsite(tag, c))
            return FunctionRecord(node=node, callsites=callsites, type_keys=[], global_keys=global_keys)
        # root
        d = occ.decl
        if d is None:
            base = os.path.basename(self.index.deck)
            node = Node(id=nid, kind="module", name=base, qualname=self._root_qual(tag), lang="sp", loc=loc,
                        signature=self.index.title or f"deck {base}", storage=None, body_hash=self.index.top_hash(), precision="syntax",
                        returns=None, params=[], globals=GlobalRefs(),
                        attrs={"title": self.index.title, "dialect": self.dialect, "files": len(self.index.files),
                               "statements": len(self.index.top_items), "guard": None, "guard_id": None})
        else:
            node = Node(id=nid, kind="module", name=d.spelled, qualname=self._root_qual(tag), lang="sp", loc=loc,
                        signature=f".subckt {d.spelled} ({' '.join(d.ports)})", storage=None, body_hash=self.index.scope_hash_of(d),
                        precision="syntax", returns=None, params=[Param(name=p, type="port", dir="inout", dir_source="heuristic") for p in d.ports],
                        globals=GlobalRefs(), attrs={"definition": d.spelled, "definition_refs": [{"guard_id": d.gid, "key": d.identity}],
                                                     "definition_file": self._rel(d.file), "defaults": dict(d.params), "dialect": self.dialect,
                                                     "guard": guard_text(d.guard) or None, "guard_id": d.gid or None})
        for c in elab.children(occ):
            callsites.append(self._child_callsite(tag, c))
        return FunctionRecord(node=node, callsites=callsites, type_keys=[], global_keys=[])

    def _child_callsite(self, tag: str, c: Occurrence) -> CallSite:
        ckey = self._key(tag, c)
        el = c.element
        loc = Loc(file=self._rel(el.file), line=el.line, end_line=el.end_line)
        if c.kind == "inst":
            parts = self._elabs[tag].instance(c).parts
            return CallSite(callee_key=ckey, name=c.name, loc=loc, kind="instance", args=list(parts.positional))
        parts = self._elabs[tag].device(c).parts
        return CallSite(callee_key=ckey, name=c.name, loc=loc, kind="instance", args=list(parts.positional))

    def _missing_key(self, tag: str, occ: Occurrence, r: dict) -> str:
        key = f"{tag}/missing:{path_str(occ.path)}|{occ.gid}:{r['as_written']}"
        if key not in self._missing:
            scope = occ.parent.path if occ.parent else ()
            self._missing[key] = {"id": _ids.node_id("sp", self._rel(self._root_file(tag)), path_str(scope + (fold(r["as_written"], self.profile.case_sensitive),)) + "?"),
                                  "name": r["as_written"], "reason": r["reason"]}
        return key

    def _global_id(self, key: str) -> str:
        return _ids.node_id("sp", self._rel(self.index.deck), f"net {self.index.globals.get(key[4:], key[4:])}")

    def declaration(self, key: str) -> Optional[DeclRecord]:
        if key in self._missing:
            m = self._missing[key]
            return DeclRecord(id=m["id"], name=m["name"], loc=None, has_definition=False, system=False, relpath=None, reason=m["reason"])
        if key not in self._occ:
            return None
        tag, occ = self._occ[key]
        loc = self._loc_of(occ, tag)
        reason = None
        has_def = True
        if occ.kind == "inst":
            elab = self._elabs[tag]
            rec = elab.instance(occ)
            if occ.decl is None:
                has_def = False
                lk = occ.lookup
                if lk is not None and lk.ambiguous:
                    where = ", ".join(f"{self._rel(d.file)}:{d.line}" for d in lk.alternatives)
                    reason = f"ambiguous: {len(lk.alternatives)} definitions of '{rec.parts.master}' in scope '{'/'.join(lk.scope_found or ())}' ({where})"
                else:
                    scope = path_str(occ.parent.path) if occ.parent else ""
                    reason = (f"no .subckt definition '{rec.parts.master}' visible from scope '{scope}' (searched deck, "
                              f"{sum(1 for f in self.index.files if f.role == 'include')} includes, lib sections {[s[1] for s in self.index.stats['sections']]})")
            elif occ.recursive:
                has_def = False
                chain = [o.decl.spelled for o in elab._ancestors(occ) if o.decl is not None]
                reason = f"recursive subcircuit instantiation ({' -> '.join(chain)})"
            elif occ.too_deep:
                has_def = False
                reason = "hierarchy deeper than 64 levels"
        return DeclRecord(id=self._id_of(tag, occ), name=occ.name or self._root_qual(tag), loc=loc, has_definition=has_def, system=False,
                          relpath=loc.file, reason=reason)

    def type(self, key: str) -> Optional[TypeRecord]:
        return None

    def global_var(self, key: str) -> Optional[GlobalVar]:
        if not key.startswith("net:"):
            return None
        f = key[4:]
        spelled = self.index.globals.get(f)
        if spelled is None:
            return None
        return GlobalVar(id=self._global_id(key), name=spelled, type="net", lang="sp", type_ref=None, loc=None, storage=None, scope="file")

    def callers(self, key: str) -> list[tuple[str, CallSite]]:
        if key not in self._occ:
            return []
        tag, occ = self._occ[key]
        if occ.parent is None:
            return []
        pkey = self._key(tag, occ.parent)
        return [(pkey, self._child_callsite(tag, occ))]

    # ------------------------------------------------------------ circuit block
    def _decl_entry(self, d: Decl, kind: str) -> dict:
        entry = {"guard_id": d.gid or None, "guard": guard_json(d.guard), "file": self._rel(d.file), "line": d.line, "end_line": d.end_line,
                 "identity": d.identity}
        if kind == "subckt":
            entry.update({"ports": list(d.ports), "params": dict(d.params), "hash": self.index.scope_hash_of(d),
                          "id": _ids.node_id("sp", self._rel(d.file), "@" + d.identity.lstrip("/"))})
        elif kind == "model":
            entry.update({"type": d.type, "params_text": d.params_text, "hash": statement_hash(d.stmt.text, self.profile)})
        else:
            entry.update({"expr": d.expr, "hash": statement_hash(f"{d.name}={d.expr}", self.profile)})
        return entry

    def _decl_record(self, decls: list[Decl], kind: str, status: str, extra: Optional[dict] = None) -> dict:
        d0 = decls[0]
        rec = {"spelled": d0.spelled, "scope": "/".join(d0.scope), "status": status, "declarations": [self._decl_entry(d, kind) for d in decls], "bins": []}
        if extra:
            rec.update(extra)
        return rec

    @staticmethod
    def _merge_status(old: str, new: str, count: int) -> str:
        if "ambiguous" in (old, new):
            return "ambiguous"
        if "binned" in (old, new):
            return "binned"
        if count > 1:
            return "alternatives"
        return old

    def _merge_record(self, store: dict, k: str, decls: list[Decl], kind: str, status: str, list_field: str, bins=()) -> dict:
        """Add declarations to the record `k`, creating it when new. Entries dedupe by (identity, file, line): two
        unguarded cards of one name share an identity (both stay, ambiguous), one file included from `.if` and
        `.else` shares a source (both stay, alternatives). A record grows across calls: each guarded device sees
        only its own branch's declaration, the record holds every branch."""
        src = list(decls) or list(bins)
        rec = store.get(k)
        if rec is None:
            d0 = src[0]
            rec = store[k] = {"spelled": d0.spelled if decls else d0.spelled.rsplit(".", 1)[0], "scope": "/".join(d0.scope),
                              "status": status, "declarations": [], "bins": [], list_field: []}
        have = {(e["identity"], e["file"], e["line"]) for e in rec["declarations"]}
        for d in src:
            e = self._decl_entry(d, kind)
            key = (e["identity"], e["file"], e["line"])
            if key not in have:
                rec["declarations"].append(e)
                have.add(key)
        rec["declarations"].sort(key=lambda e: (e["file"], e["line"], e["identity"]))
        for b in bins:
            if b.name not in rec["bins"]:
                rec["bins"].append(b.name)
        rec["status"] = self._merge_status(rec["status"], status, len(rec["declarations"]))
        return rec

    def finalize(self, graph) -> None:
        """Attach the circuit block (restricted to graph nodes) plus meta.deps / meta.probes."""
        cs = self.profile.case_sensitive
        definitions: dict[str, dict] = {}
        models: dict[str, dict] = {}
        params: dict[str, dict] = {}
        nets: dict[str, dict] = {}
        terminals: dict[str, list] = {}
        ports: dict[str, list] = {}
        diag_nodes: list[dict] = []
        scopes_seen: set[tuple] = set()
        elabs_used: set[str] = set()

        def key_of(d: Decl) -> str:
            return ("/".join(d.scope) + "/" if d.scope else "/") + d.name

        def add_definition(decls: list[Decl], status: str, instances: list[str]) -> None:
            rec = self._merge_record(definitions, key_of(decls[0]), decls, "subckt", status, "instances")
            for i in instances:
                if i not in rec["instances"]:
                    rec["instances"].append(i)

        def add_model(decls: list[Decl], status: str, used_by: str, bins: list[Decl] = ()) -> None:
            if not decls and not bins:
                return
            k = key_of(decls[0]) if decls else key_of(bins[0]).rsplit(".", 1)[0]
            rec = self._merge_record(models, k, decls, "model", status, "used_by", bins)
            if used_by not in rec["used_by"]:
                rec["used_by"].append(used_by)

        def add_net(elab: Elaborator, key: str) -> None:
            if key in nets:
                return
            n = elab.nets.get(key)
            if n is None:
                nets[key] = {"spelled": key.rsplit(".", 1)[-1], "scope": "", "kind": "global" if key in self.index.globals else ("ground" if key == "0" else "internal"),
                             "bindings": [], "terminals": []}
                return
            # each binding's canonical net follows the chain of the instance that made it
            nets[key] = {"spelled": n.spelled, "scope": n.scope, "kind": n.kind,
                         "bindings": [{"via": self._occ_id_by_key(b["via"]), "outer": b["outer"], "canonical": elab.canonical(key, elab._by_key.get(b["via"]))} for b in n.bindings],
                         "terminals": [[self._occ_id_by_key(t[0]), t[1]] for t in n.terminals if self._occ_id_by_key(t[0]) in graph.nodes]}
            for b in n.bindings:
                add_net(elab, b["outer"])

        for nid in graph.nodes:
            key = self._by_id.get(nid)
            if key is None:
                continue
            tag, occ = self._occ[key]
            elab = self._elabs[tag]
            elabs_used.add(tag)
            if occ.kind == "dev":
                rec = elab.device(occ)
                terminals[nid] = [{"terminal": t["terminal"], "net": t["net"], "canonical": elab.canonical(t["net"], occ), "as_written": t["as_written"]}
                                  for t in rec.terminals]
                for t in rec.terminals:
                    add_net(elab, t["net"])
                lk = rec.model_lookup
                if lk is not None and lk.found:
                    add_model(lk.alternatives, rec.model_status or "found", nid, lk.bins)
                elif rec.model_status == "missing" and rec.parts.master:
                    k = "/" + fold(rec.parts.master, cs)
                    models.setdefault(k, {"spelled": rec.parts.master, "scope": "", "status": "missing", "declarations": [], "bins": [], "used_by": []})
                    if nid not in models[k]["used_by"]:
                        models[k]["used_by"].append(nid)
                for d in rec.diagnostics:
                    d["node"] = nid
                scopes_seen.add(elab.body_scope(occ.parent) if occ.parent else ())
            elif occ.kind == "inst":
                rec = elab.instance(occ)
                ports[nid] = [{"port": b["port"], "inner": b["inner"], "outer": b["outer"], "net": elab.canonical(b["outer"], occ), "as_written": b["as_written"]} for b in rec.bindings]
                for b in rec.bindings:
                    add_net(elab, b["inner"])
                    add_net(elab, b["outer"])
                if occ.decl is not None:
                    add_definition([occ.decl], "alternatives" if occ.lookup and len(occ.lookup.alternatives) > 1 else "found", [nid])
                    scopes_seen.add(occ.decl.body_scope)
                elif occ.lookup is not None and occ.lookup.alternatives:
                    add_definition(occ.lookup.alternatives, "ambiguous", [nid])
                for d in rec.diagnostics:
                    d["node"] = nid
            else:
                if occ.decl is not None:
                    add_definition([occ.decl], "found", [nid])
                    scopes_seen.add(occ.decl.body_scope)
                else:
                    scopes_seen.add(())
        # ghosts: an ambiguous or missing instance never becomes a node, but its candidates (or its absence) belong to
        # the block; the body stays unexpanded
        for u in graph.unresolved:
            key = self._by_id.get(getattr(u, "id", None) or "")
            if key is None or key not in self._occ:
                continue
            tag, occ = self._occ[key]
            if occ.kind != "inst" or occ.decl is not None:
                continue
            lk = occ.lookup
            if lk is not None and lk.alternatives:
                add_definition(lk.alternatives, "ambiguous" if lk.ambiguous else "found", [u.id])
            else:
                master = self._elabs[tag].instance(occ).parts.master or "?"
                k = "/" + fold(master, cs)
                definitions.setdefault(k, {"spelled": master, "scope": "", "status": "missing", "declarations": [], "bins": [], "instances": []})
                if u.id not in definitions[k]["instances"]:
                    definitions[k]["instances"].append(u.id)
        for d in self.index.all_decls("param"):
            if d.scope in scopes_seen:
                k = key_of(d)
                if k not in params:
                    params[k] = self._decl_record([x for x in self.index.decls[("param", d.scope, d.name)]], "param", "found")
        # shadowing: an inner declaration hides an outer one of the same name
        for k, rec in list(definitions.items()) + list(models.items()):
            if rec["scope"]:
                kind = "subckt" if k in definitions else "model"
                outer = self.index.shadowed(kind, tuple(rec["scope"].split("/")), rec["spelled"])
                if outer:
                    ok = key_of(outer[0])
                    target = definitions if kind == "subckt" else models
                    if ok not in target:
                        target[ok] = self._decl_record(outer, kind, "shadowed", {"instances": []} if kind == "subckt" else {"used_by": []})
        self._refresh_diagnostics()
        root_tag = next(iter(elabs_used), "deck")
        graph.circuit = {
            "dialect": self.dialect, "deck": self._rel(self.index.deck),
            "root": {"kind": "deck" if root_tag == "deck" else "definition", "id": graph.entry, "deck_role": self.deck_role},
            "files": [{"path": self._rel(f.path), "role": f.role, "section": f.section, "from": {"file": f.from_file, "line": f.from_line} if f.from_file else None,
                       "resolved_by": f.resolved_by, "outside_root": f.outside_root} for f in self.index.files],
            "definitions": definitions, "models": models, "params": params, "nets": nets, "terminals": terminals, "ports": ports,
            "directives": list(self.index.directives), "control_blocks": list(self.index.control_blocks),
            "probes": list(self.index.probes), "diagnostics": list(self.diagnostics),
        }
        graph.meta["deps"] = [self._rel(p) if p.startswith(self.root + os.sep) else p for p in self.deps]
        graph.meta["probes"] = [{"requested": p["requested"], "candidates": p["candidates"], "resolved": p["resolved"]} for p in self.index.probes]
        self._count_diags()
        graph.meta["notes"] = list(self.notes)
        graph.meta["index"] = dict(self.stats)

    def _occ_id_by_key(self, occ_key: str) -> str:
        for k, (tag, occ) in self._occ.items():
            if occ.key == occ_key:
                return self._id_of(tag, occ)
        # not yet registered under a tag (a net touched only by an occurrence outside the graph)
        for tag, elab in self._elabs.items():
            for lst in elab._children.values():
                for c in lst:
                    if c.key == occ_key:
                        return self._id_of(tag, c)
        return occ_key
