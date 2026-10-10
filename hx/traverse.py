"""Depth-limited BFS over a Frontend, producing a Graph.

Callee side: depth 0 = entry, 1 = direct callees, ... up to --depth.
Caller side (--include-callers): depth -1 = direct callers, -2 = their callers.
Anything reached but not expanded (beyond depth, excluded, system, no
definition, function pointer) is listed in `unresolved` with a reason, so the
viewer can render it as a ghost node instead of silently dropping it.
"""
from __future__ import annotations

import fnmatch
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .frontends.base import Frontend, CallSite, FunctionRecord
from .model import Graph, Edge, Unresolved, Node


@dataclass
class TraverseOptions:
    depth: Optional[int] = 3          # None = unlimited
    type_depth: int = 2
    include_callers: bool = False
    include_system: bool = False
    exclude: list[str] = field(default_factory=list)
    max_nodes: Optional[int] = None


class _Builder:
    def __init__(self, fe: Frontend, opts: TraverseOptions, graph: Graph):
        self.fe = fe
        self.opts = opts
        self.g = graph
        self.seen_unresolved: set[tuple] = set()
        self.truncated = False
        self.type_level: dict[str, int] = {}   # type id -> smallest nesting level it was expanded at

    # -- helpers -----------------------------------------------------------
    def excluded(self, relpath: Optional[str]) -> bool:
        if not relpath:
            return False
        return any(fnmatch.fnmatch(relpath, pat) for pat in self.opts.exclude)

    def unresolved(self, name: str, src: str, reason: str, loc, uid: Optional[str]) -> None:
        key = (uid or name, src, reason)
        if key in self.seen_unresolved:
            return
        self.seen_unresolved.add(key)
        self.g.unresolved.append(Unresolved(name=name, src=src, reason=reason, loc=loc, id=uid))

    def edge_from(self, src_id: str, cs: CallSite, dst_id: Optional[str]) -> Edge:
        e = Edge(src=src_id, dst=dst_id, kind=cs.kind, loc=cs.loc, args=list(cs.args),
                 name=cs.name, macro=cs.macro, ptr_type=cs.ptr_type)
        self.g.edges.append(e)
        return e

    def add_type(self, key: str, level: int, used_by: Optional[str]) -> None:
        """Record a type and expand its nested types down to --type-depth. A type met again at a SMALLER level
        (closer to a signature) is re-expanded with the larger remaining budget, so the result does not depend
        on traversal order."""
        rec = self.fe.type(key)
        if rec is None:
            return
        td = rec.typedef
        existing = self.g.types.get(td.id)
        if existing is None:
            self.g.types[td.id] = td
            existing = td
        if used_by and used_by not in existing.used_by:
            existing.used_by.append(used_by)
        prev = self.type_level.get(td.id)
        if prev is not None and prev <= level:
            return  # already expanded with at least this much budget
        self.type_level[td.id] = level
        for ak in rec.alias_keys:
            self.add_type(ak, level, None)
        if level < self.opts.type_depth:
            for nk in rec.nested_keys:
                self.add_type(nk, level + 1, None)

    def add_node(self, node: Node, depth: int) -> bool:
        if node.id in self.g.nodes:
            prev = self.g.nodes[node.id]
            if abs(depth) < abs(prev.depth):
                prev.depth = depth
            return False
        if self.opts.max_nodes is not None and len(self.g.nodes) >= self.opts.max_nodes:
            self.truncated = True
            return False
        node.depth = depth
        self.g.nodes[node.id] = node
        return True

    # -- expansion decision ---------------------------------------------------
    def can_expand(self, key: str, src_id: str, cs: CallSite, next_depth: int) -> Optional[str]:
        """Return the target id, after recording the edge; None if not expandable."""
        decl = self.fe.declaration(key)
        target_id = decl.id if decl else self.fe.stable_id(key)
        self.edge_from(src_id, cs, target_id)
        if decl is None:
            self.unresolved(cs.name, src_id, "unknown symbol", cs.loc, target_id)
            return None
        if self.excluded(decl.relpath):
            self.unresolved(decl.name, src_id, "excluded by filter", cs.loc, decl.id)
            return None
        if decl.system and not self.opts.include_system:
            self.unresolved(decl.name, src_id, decl.reason or "system header excluded", cs.loc, decl.id)
            return None
        if not decl.has_definition:
            self.unresolved(decl.name, src_id, decl.reason or "no definition in TU set", cs.loc, decl.id)
            return None
        if self.opts.depth is not None and abs(next_depth) > self.opts.depth:
            self.unresolved(decl.name, src_id, "beyond depth limit", cs.loc, decl.id)
            return None
        return target_id

    # -- passes -----------------------------------------------------------
    def add_globals(self, rec: FunctionRecord) -> None:
        for gk in rec.global_keys:
            gv = self.fe.global_var(gk)
            if gv is not None and gv.id not in self.g.globals:
                self.g.globals[gv.id] = gv

    def truncate(self, queue: deque, reason: str = "truncated by --max-nodes") -> None:
        """--max-nodes reached: every queued-but-unexpanded target gets an unresolved record whose `from` is
        the node that reached it (always in the graph), so nothing disappears silently."""
        self.truncated = True
        while queue:
            key, _d, parent_id, cs = queue.popleft()
            if parent_id is None:
                continue
            decl = self.fe.declaration(key)
            name = cs.name if cs else (decl.name if decl else key)
            self.unresolved(name, parent_id, reason, cs.loc if cs else (decl.loc if decl else None),
                            decl.id if decl else self.fe.stable_id(key))

    # -- passes -----------------------------------------------------------
    def callees(self, entry_key: str) -> None:
        queue: deque = deque([(entry_key, 0, None, None)])     # (key, depth, parent id, call site)
        seen = {entry_key}
        while queue:
            key, d, parent_id, pcs = queue.popleft()
            rec = self.fe.function(key)
            if rec is None:
                continue
            node = rec.node
            if not self.add_node(node, d):
                if self.truncated:
                    queue.appendleft((key, d, parent_id, pcs))
                    self.truncate(queue)
                    break
                continue
            for cs in rec.callsites:
                if cs.callee_key is None:
                    self.edge_from(node.id, cs, None)
                    self.unresolved(cs.name, node.id, "indirect call through function pointer", cs.loc, None)
                    continue
                if cs.callee_key in seen:
                    # already expanded (or queued): recursion / shared callee. Edge only, no depth check.
                    target_id = self.fe.stable_id(cs.callee_key)
                    self.edge_from(node.id, cs, target_id)
                    if target_id and target_id not in node.calls:
                        node.calls.append(target_id)
                    continue
                target_id = self.can_expand(cs.callee_key, node.id, cs, d + 1)
                if target_id and target_id not in node.calls:
                    node.calls.append(target_id)
                if target_id is None:
                    continue
                seen.add(cs.callee_key)
                queue.append((cs.callee_key, d + 1, node.id, cs))
            for tk in rec.type_keys:
                self.add_type(tk, 0, node.id)
            self.add_globals(rec)

    def callers(self, entry_key: str) -> None:
        queue: deque = deque([(entry_key, 0)])
        seen = {entry_key}
        while queue:
            key, d = queue.popleft()
            callee_id = self.fe.stable_id(key)
            if self.opts.depth is not None and abs(d - 1) > self.opts.depth:
                continue
            for caller_key, cs in self.fe.callers(key):
                rec = self.fe.function(caller_key)
                if rec is None:
                    continue
                node = rec.node
                decl = self.fe.declaration(caller_key)
                if decl and (self.excluded(decl.relpath) or (decl.system and not self.opts.include_system)):
                    continue
                if node.id not in self.g.nodes:
                    if self.opts.max_nodes is not None and len(self.g.nodes) >= self.opts.max_nodes:
                        # the caller would not fit: no edge from a node that is not in the graph, just the record
                        self.truncated = True
                        if callee_id:
                            self.unresolved(node.name, callee_id, "caller truncated by --max-nodes", cs.loc, node.id)
                        continue
                    self.add_node(node, d - 1)
                    for tk in rec.type_keys:
                        self.add_type(tk, 0, node.id)
                    self.add_globals(rec)
                self.edge_from(node.id, cs, callee_id)
                if callee_id and callee_id not in node.calls:
                    node.calls.append(callee_id)
                if caller_key not in seen:
                    seen.add(caller_key)
                    queue.append((caller_key, d - 1))


def extract_graph(fe: Frontend, entry_file: str, entry_symbol: str, opts: TraverseOptions, root: str) -> Graph:
    entry_key = fe.locate_entry(entry_file, entry_symbol)
    entry_id = fe.stable_id(entry_key) or entry_key
    graph = Graph(root=root, lang=fe.lang, entry=entry_id)
    b = _Builder(fe, opts, graph)
    b.callees(entry_key)
    if opts.include_callers and not b.truncated:
        b.callers(entry_key)
    graph.meta["truncated"] = b.truncated
    graph.meta["options"] = {
        "depth": opts.depth, "type_depth": opts.type_depth, "include_callers": opts.include_callers,
        "include_system": opts.include_system, "exclude": list(opts.exclude), "max_nodes": opts.max_nodes,
    }
    return graph
