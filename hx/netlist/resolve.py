"""Elaborator: lazy hierarchy of occurrences (one instance or device at one path under one guard), their terminal
nets, port bindings, controlling references, recursion and depth checks. Nothing is guessed: a definition that is
missing, ambiguous or recursive leaves the occurrence unexpanded with a reason."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Optional

from .grammar import ElementParts, grammar_for
from .index import Decl, DesignIndex, Lookup
from .names import EMPTY_GUARD, Guard, escape_segment, fold, guard_compatible, guard_id, guard_union, path_str
from .parser import Element, Stmt
from .profiles import Family
from .. import ids as _ids

MAX_HIER_DEPTH = 64


@dataclass
class Occurrence:
    path: tuple[str, ...]                       # folded segments (root = ())
    spelled: tuple[str, ...]
    guard: Guard
    kind: str                                   # root | inst | dev
    element: Optional[Element] = None
    decl: Optional[Decl] = None                 # inst / subckt-rooted root: the definition
    parent: Optional["Occurrence"] = None
    lookup: Optional[Lookup] = None
    recursive: bool = False
    too_deep: bool = False
    dup_suffix: str = ""

    @property
    def gid(self) -> str:
        return guard_id(self.guard)

    @property
    def suffix(self) -> str:
        """Id/key suffix: `#<guard_id>` for a guarded occurrence, then `~<hash>` for a position-dependent duplicate."""
        return (f"#{self.gid}" if self.gid else "") + self.dup_suffix

    @property
    def key(self) -> str:
        return f"{self.kind}:{path_str(self.path)}|{self.gid}{self.dup_suffix}"

    @property
    def name(self) -> str:
        return self.spelled[-1] if self.spelled else ""

    @property
    def folded(self) -> str:
        return self.path[-1] if self.path else ""


@dataclass
class InstanceRecord:
    occ: Occurrence
    parts: ElementParts
    definition: Optional[Decl]
    bindings: list[dict] = field(default_factory=list)      # {port, inner, outer, as_written}
    unbound: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)


@dataclass
class DeviceRecord:
    occ: Occurrence
    family: Optional[Family]
    parts: ElementParts
    terminals: list[dict] = field(default_factory=list)     # {terminal, net, as_written}
    model_refs: list[dict] = field(default_factory=list)    # {guard_id, key}
    model_status: Optional[str] = None
    model_lookup: Optional[Lookup] = None
    refs: list[dict] = field(default_factory=list)          # {role, as_written, targets: [Occurrence], reason}
    diagnostics: list[dict] = field(default_factory=list)


@dataclass
class NetRecord:
    key: str
    spelled: str
    scope: str
    kind: str                                               # internal | port | global | ground
    bindings: list[dict] = field(default_factory=list)      # {via: occurrence key, canonical}
    terminals: list[list] = field(default_factory=list)     # [occurrence key, terminal]


class Elaborator:
    def __init__(self, index: DesignIndex, root_kind: str = "deck", root_decl: Optional[Decl] = None):
        self.index = index
        self.profile = index.profile
        self.grammar = grammar_for(self.profile)
        self.root_kind = root_kind
        self.root = Occurrence(path=(), spelled=(), guard=EMPTY_GUARD, kind="root", decl=root_decl)
        self._by_key: dict[str, Occurrence] = {self.root.key: self.root}   # every occurrence created, by key
        self._children: dict[str, list[Occurrence]] = {}
        self._inst: dict[str, InstanceRecord] = {}
        self._dev: dict[str, DeviceRecord] = {}
        self.nets: dict[str, NetRecord] = {}
        self.diagnostics: list[dict] = []

    # ------------------------------------------------------------ bodies and scopes
    def body_items(self, occ: Occurrence) -> list[tuple[Stmt, Guard]]:
        if occ.kind == "root" and occ.decl is None:
            return self.index.top_items
        return list(occ.decl.items) if occ.decl else []

    def body_scope(self, occ: Occurrence) -> tuple:
        if occ.decl is None:
            return ()
        return occ.decl.body_scope

    def _diag(self, code: str, message: str, occ: Occurrence, severity: str = "error") -> dict:
        el = occ.element
        d = {"severity": severity, "code": code, "message": message, "file": self.index._rel(el.file) if el else None,
             "line": el.line if el else None, "node": None, "scope": path_str(occ.parent.path) if occ.parent else ""}
        self.diagnostics.append(d)
        return d

    # ------------------------------------------------------------ children
    def children(self, occ: Occurrence) -> list[Occurrence]:
        if occ.key in self._children:
            return self._children[occ.key]
        out: list[Occurrence] = []
        if occ.recursive or occ.too_deep or (occ.kind == "inst" and occ.decl is None):
            self._children[occ.key] = out
            return out
        cs = self.profile.case_sensitive
        scope = self.body_scope(occ)
        groups: dict[str, list[tuple[Element, Guard]]] = {}
        order: list[str] = []
        for st, g in self.body_items(occ):
            if not isinstance(st, Element):
                continue
            f = fold(st.name, cs)
            if f not in groups:
                order.append(f)
            groups.setdefault(f, []).append((st, guard_union(occ.guard, g)))
        for f in order:
            members = groups[f]
            # the same name twice in one body: alternatives when their guards are mutually exclusive, else a
            # guarded-duplicate (both kept, the later one under a position-dependent suffix)
            seen: list[tuple[Element, Guard]] = []
            for st, g in members:
                dup = any(guard_compatible(g, g2) for _s, g2 in seen)
                seen.append((st, g))
                suffix = ""
                if dup:
                    suffix = "~" + _ids.short_hash(f"{self.index._rel(st.file)}:{st.line}", 8)
                    self.diagnostics.append({"severity": "error", "code": "guarded-duplicate",
                                             "message": f"{st.name} is declared twice in one scope under compatible guards ({self.index._rel(st.file)}:{st.line}); kept under {f}{suffix}",
                                             "file": self.index._rel(st.file), "line": st.line, "node": None, "scope": path_str(occ.path)})
                if st.letter == "X":
                    out += self._instance_children(occ, st, g, f, scope, suffix)
                else:
                    out.append(Occurrence(path=occ.path + (f,), spelled=occ.spelled + (st.name,), guard=g, kind="dev",
                                          element=st, parent=occ, dup_suffix=suffix))
        for c in out:
            self._by_key[c.key] = c
        self._children[occ.key] = out
        return out

    def _instance_children(self, parent: Occurrence, st: Element, g: Guard, seg: str, scope: tuple, suffix: str = "") -> list[Occurrence]:
        fam = self.profile.families.get("X")
        parts = self.grammar.split_element(st.tokens(self.profile), fam, lambda _n: False)
        master = parts.master or ""
        lk = self.index.lookup("subckt", scope, master, g) if master else Lookup(alternatives=[])
        out: list[Occurrence] = []
        if lk.ambiguous or not lk.alternatives:
            out.append(Occurrence(path=parent.path + (seg,), spelled=parent.spelled + (st.name,), guard=g, kind="inst",
                                  element=st, decl=None, parent=parent, lookup=lk, dup_suffix=suffix))
            return out
        for d in lk.alternatives:
            og = guard_union(g, d.guard)
            occ = Occurrence(path=parent.path + (seg,), spelled=parent.spelled + (st.name,), guard=og, kind="inst",
                             element=st, decl=d, parent=parent, lookup=lk, dup_suffix=suffix)
            # recursion: the same definition on the ancestor chain
            p = parent
            while p is not None:
                if p.decl is not None and p.decl is d:
                    occ.recursive = True
                    break
                p = p.parent
            if len(occ.path) > MAX_HIER_DEPTH:
                occ.too_deep = True
            out.append(occ)
        return out

    def find_children(self, parent: Occurrence, folded_name: str, guard: Guard, letters: tuple[str, ...] = ()) -> list[Occurrence]:
        """Every child of `parent` with that name whose guard is compatible with the requester's: alternatives when
        they exclude each other, a guarded duplicate (position-suffixed) among them makes the reference ambiguous."""
        return [c for c in self.children(parent)
                if c.path[-1] == folded_name and guard_compatible(c.guard, guard) and (not letters or (c.element and c.element.letter in letters))]

    # ------------------------------------------------------------ nets
    def net_key(self, scope_occ: Occurrence, name: str) -> str:
        cs = self.profile.case_sensitive
        f = fold(name, cs)
        if f in self.profile.ground_names:
            return "0"
        if f in self.index.globals or (self.profile.name == "xyce" and f.startswith("$g")):
            return f
        return path_str(scope_occ.path + (f,))

    def _net(self, key: str, spelled: str, scope_occ: Occurrence, kind: str) -> NetRecord:
        if key == "0":
            kind, spelled = "ground", "0"
        elif key in self.index.globals:
            kind = "global"
        n = self.nets.get(key)
        if n is None:
            n = NetRecord(key=key, spelled=spelled, scope="" if kind in ("global", "ground") else path_str(scope_occ.path), kind=kind)
            self.nets[key] = n
        return n

    def _ensure_bindings(self, occ: Optional[Occurrence]) -> None:
        """Port bindings exist for every instance on the way to the root, whatever order records were requested in."""
        chain = []
        p = occ
        while p is not None:
            chain.append(p)
            p = p.parent
        for o in reversed(chain):
            if o.kind == "inst" and o.key not in self._inst:
                self.instance(o)

    def net_kind(self, scope_occ: Occurrence, name: str) -> str:
        f = fold(name, self.profile.case_sensitive)
        if f in self.profile.ground_names:
            return "ground"
        if f in self.index.globals or (self.profile.name == "xyce" and f.startswith("$g")):
            return "global"
        if scope_occ.decl is not None and f in {fold(p, self.profile.case_sensitive) for p in scope_occ.decl.ports}:
            return "port"
        return "internal"

    def ancestor_keys(self, occ: Optional[Occurrence]) -> set[str]:
        out, p = set(), occ
        while p is not None:
            out.add(p.key)
            p = p.parent
        return out

    def canonical(self, key: str, occ: Optional[Occurrence] = None) -> str:
        """Follow port bindings outward along `occ`'s ancestor chain: at every level the binding made by the instance
        that encloses the request there (two guarded `xw` occurrences bind `xw.in` differently; a device under one
        of them must take its own). Without a chain a single binding is followed; several bindings and no ancestor
        among them stop the walk (nothing is guessed)."""
        chain = self.ancestor_keys(occ)
        seen = set()
        while key not in seen:
            seen.add(key)
            n = self.nets.get(key)
            if not n or not n.bindings:
                return key
            b = next((b for b in n.bindings if b["via"] in chain), None)
            if b is None:
                if occ is None and len(n.bindings) == 1:
                    b = n.bindings[0]
                else:
                    return key
            key = b["outer"]
        return key

    # ------------------------------------------------------------ records
    def instance(self, occ: Occurrence) -> InstanceRecord:
        if occ.key in self._inst:
            return self._inst[occ.key]
        st = occ.element
        parts = self.grammar.split_element(st.tokens(self.profile), self.profile.families.get("X"), lambda _n: False)
        rec = InstanceRecord(occ=occ, parts=parts, definition=occ.decl)
        parent = occ.parent
        if occ.decl is None:
            lk = occ.lookup
            if lk is not None and lk.ambiguous:
                where = ", ".join(f"{self.index._rel(d.file)}:{d.line}" for d in lk.alternatives)
                rec.diagnostics.append(self._diag("duplicate-definition", f"ambiguous: {len(lk.alternatives)} definitions of '{parts.master}' in scope '{'/'.join(lk.scope_found or ())}' ({where})", occ))
            else:
                rec.diagnostics.append(self._diag("missing-definition", f"no .subckt definition '{parts.master}' visible from scope '{path_str(parent.path) if parent else ''}'", occ))
        else:
            self._ensure_bindings(parent)
            ports = occ.decl.ports
            nets = parts.positional
            for i, port in enumerate(ports):
                inner = self.net_key(occ, port)
                self._net(inner, port, occ, "port")
                if i < len(nets):
                    outer = self.net_key(parent, nets[i])
                    self._net(outer, nets[i], parent, self.net_kind(parent, nets[i]))
                    rec.bindings.append({"port": port, "inner": inner, "outer": outer, "as_written": nets[i]})
                    if inner in ("0",) or inner in self.index.globals:
                        continue                                  # a port named like a global IS the global: nothing to bind
                    nb = self.nets[inner].bindings
                    if not any(b["via"] == occ.key for b in nb):
                        nb.append({"via": occ.key, "outer": outer, "canonical": None})
                else:
                    rec.unbound.append(port)
            rec.extra = nets[len(ports):]
            if rec.unbound or rec.extra:
                rec.diagnostics.append(self._diag("terminal-count-mismatch",
                                                  f"{st.name}: {len(nets)} nets for {len(ports)} ports of {occ.decl.spelled} (unbound {rec.unbound}, extra {rec.extra})", occ))
            if occ.recursive:
                chain = [o.decl.spelled for o in self._ancestors(occ) if o.decl is not None]
                rec.diagnostics.append(self._diag("recursive-hierarchy", f"recursive subcircuit instantiation ({' -> '.join(chain)})", occ))
            if occ.too_deep:
                rec.diagnostics.append(self._diag("hierarchy-too-deep", f"hierarchy deeper than {MAX_HIER_DEPTH} levels", occ))
        self._inst[occ.key] = rec
        return rec

    def _ancestors(self, occ: Occurrence) -> list[Occurrence]:
        out, p = [], occ
        while p is not None:
            out.append(p)
            p = p.parent
        return list(reversed(out))

    def device(self, occ: Occurrence) -> DeviceRecord:
        if occ.key in self._dev:
            return self._dev[occ.key]
        st = occ.element
        parent = occ.parent
        self._ensure_bindings(parent)
        scope = self.body_scope(parent)
        fam = self.profile.families.get(st.letter)
        is_model = lambda n: self.index.is_model_visible(scope, n, occ.guard)
        parts = self.grammar.split_element(st.tokens(self.profile), fam, is_model)
        if self.profile.name == "xyce" and fam and parts.master:
            import re
            from dataclasses import replace
            from .profiles import XYCE_INVENTORY
            lookup = self.index.lookup("model", scope, parts.master, occ.guard)
            if len(lookup.alternatives) == 1:
                decl = lookup.alternatives[0]
                match = re.search(r"\blevel\s*=\s*(\d+)", decl.params_text or "", re.I)
                level = match.group(1) if match else "1"
                family_key = fam.letter[1:].lower() if fam.letter.startswith("Y") else fam.letter.lower()
                spec = XYCE_INVENTORY["families"].get(family_key, {}).get(level)
                if spec:
                    fam = replace(fam, min_terminals=int(spec["nodes"]), max_terminals=int(spec["nodes"]) + int(spec["optional"]))
                    parts = self.grammar.split_element(st.tokens(self.profile), fam, is_model)
        rec = DeviceRecord(occ=occ, family=fam, parts=parts)
        if fam is None:
            rec.diagnostics.append(self._diag("unknown-device-family", f"{st.name}: no device family for letter {st.letter!r}; tokens kept", occ, "warning"))
        else:
            if self.profile.name == "xyce" and not fam.min_terminals <= len(parts.positional) <= fam.max_terminals and not any(m.startswith("only ") for m in parts.diagnostics):
                rec.diagnostics.append(self._diag("terminal-count-mismatch", f"{st.name}: {len(parts.positional)} terminals outside {fam.min_terminals}..{fam.max_terminals}", occ))
            names = list(fam.terminals or ())
            for i, net in enumerate(parts.positional):
                tname = names[i] if i < len(names) else f"t{i + 1}"
                key = self.net_key(parent, net)
                n = self._net(key, net, parent, self.net_kind(parent, net))
                n.terminals.append([occ.key, tname])
                rec.terminals.append({"terminal": tname, "net": key, "as_written": net})
            for msg in parts.diagnostics:
                if msg.startswith("only "):
                    rec.diagnostics.append(self._diag("terminal-count-mismatch", f"{st.name}: {msg}", occ))
            if fam.model != "none" and parts.master:
                lk = self.index.lookup("model", scope, parts.master, occ.guard)
                rec.model_lookup = lk
                if lk.ambiguous:
                    rec.model_status = "ambiguous"
                    rec.diagnostics.append(self._diag("ambiguous-model", f"{st.name}: {len(lk.alternatives)} compatible declarations of model '{parts.master}'", occ))
                elif lk.alternatives:
                    rec.model_status = "alternatives" if len(lk.alternatives) > 1 else "found"
                    rec.model_refs = [{"guard_id": d.gid, "key": d.identity} for d in lk.alternatives]
                elif lk.bins:
                    rec.model_status = "binned"
                    rec.model_refs = [{"guard_id": d.gid, "key": d.identity} for d in lk.bins]
                else:
                    rec.model_status = "missing"
                    rec.diagnostics.append(self._diag("missing-model", f"{st.name}: model '{parts.master}' not found", occ))
            elif fam.model == "required" and not parts.master:
                rec.model_status = "missing"
                rec.diagnostics.append(self._diag("missing-model", f"{st.name}: no model given", occ))
            roles = (("inductor",) * len(parts.refs)) if self.profile.name == "xyce" and fam.letter == "K" else fam.refs
            for role, as_written in zip(roles, parts.refs):
                letters = ("V",) if role == "vsource" else ("L",) if role == "inductor" else ()
                targets = self.find_children(parent, fold(as_written, self.profile.case_sensitive), occ.guard, letters)
                entry = {"role": role, "as_written": as_written, "targets": targets, "reason": None}
                if not targets:
                    entry["reason"] = f"control reference '{as_written}' not found in scope '{path_str(parent.path)}'"
                    rec.diagnostics.append(self._diag("missing-reference", entry["reason"], occ))
                elif any(guard_compatible(a.guard, b.guard) for a, b in itertools.combinations(targets, 2)):
                    rec.diagnostics.append(self._diag("ambiguous-reference",
                                                      f"{st.name}: reference '{as_written}' matches {len(targets)} declarations under compatible guards "
                                                      f"({', '.join(path_str(t.path) + t.suffix for t in targets)})", occ))
                rec.refs.append(entry)
        self._dev[occ.key] = rec
        return rec
