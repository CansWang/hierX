"""MCP server: agents query hx graphs (compact text) instead of re-reading source files.

Tools return short Markdown/plain text on purpose: the whole point is to spend
fewer tokens than grepping. Run with `hx mcp --root <project>` (stdio).
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from mcp.server.mcpserver import MCPServer

from . import annotations as ann_mod
from . import project
from .diff import diff_graphs, render_markdown


class GraphStore:
    """Loads graphs by name (tracked slug or 'graph'), cached by mtime."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self._cache: dict[str, tuple[int, dict]] = {}

    def available(self) -> list[dict]:
        return project.find_graphs(self.root)

    def resolve(self, name: str = "") -> Optional[dict]:
        graphs = self.available()
        if not graphs:
            return None
        if not name:
            return graphs[0]
        for g in graphs:
            if g["name"] == name or g["entry"] == name or g["entry_arg"] == name or project.slug(name) == g["name"]:
                return g
        return None

    def load(self, name: str = "") -> tuple[dict, dict]:
        info = self.resolve(name)
        if info is None:
            raise LookupError("no graphs yet: run `hx update` (tracked entries) or the `extract` tool" if not name
                              else f"unknown graph {name!r}; call list_graphs")
        m = os.stat(info["path"]).st_mtime_ns
        hit = self._cache.get(info["path"])
        if hit and hit[0] == m:
            return info, hit[1]
        g = project.load_graph(info["path"])
        self._cache[info["path"]] = (m, g)
        return info, g


# ---------------------------------------------------------------- formatting

def _short(i: Optional[str]) -> str:
    return i.split(":", 1)[1] if i and "::" in i else (i or "?")


def fmt_node(n: dict, g: dict, ann: Optional[dict] = None) -> str:
    out = [f"{n['id']}  [{n['kind']}, {n['lang']}, {n.get('storage') or ''} depth {n['depth']}, precision {n['precision']}]".replace(",  depth", ", depth"),
           f"  {n['loc']['file']}:{n['loc']['line']}" + (f"-{n['loc']['end_line']}" if n['loc'].get('end_line') else ""),
           f"  {n['signature']}"]
    if n.get("params"):
        out.append("  params: " + "; ".join(f"{p['name']}: {p['type']} [{p['dir']}{'' if p['dir_source'] == 'explicit' else ' ' + p['dir_source']}]" +
                                           (f" -> {p['type_ref']}" if p.get("type_ref") else "") for p in n["params"]))
    if n.get("returns") and n["returns"].get("type") not in (None, "void"):
        out.append(f"  returns: {n['returns']['type']}" + (f" -> {n['returns']['type_ref']}" if n["returns"].get("type_ref") else ""))
    gl = n.get("globals") or {}
    if gl.get("reads") or gl.get("writes"):
        out.append(f"  globals: reads {', '.join(_short(x) for x in gl.get('reads', [])) or '-'}; writes {', '.join(_short(x) for x in gl.get('writes', [])) or '-'}")
    if n.get("attrs"):
        extras = {k: v for k, v in n["attrs"].items() if k != "signals"}
        if extras:
            out.append("  attrs: " + json.dumps(extras, ensure_ascii=False))
        if n["attrs"].get("signals"):
            out.append(f"  signals: {len(n['attrs']['signals'])} internal")
    calls = [e for e in g.get("edges", []) if e["from"] == n["id"]]
    if calls:
        out.append("  calls:")
        for e in calls[:40]:
            tgt = _short(e["to"]) if e.get("to") else f"({e.get('name')})"
            out.append(f"    {e['kind']:8} {tgt}({', '.join(e.get('args') or [])})" + (f" via {e['macro']}" if e.get("macro") else "") +
                       (f"  @{e['loc']['file']}:{e['loc']['line']}" if e.get("loc") else ""))
        if len(calls) > 40:
            out.append(f"    … {len(calls) - 40} more")
    inc = [e for e in g.get("edges", []) if e.get("to") == n["id"]]
    if inc:
        out.append("  called by: " + ", ".join(sorted({_short(e["from"]) for e in inc})))
    unres = [u for u in g.get("unresolved", []) if u["from"] == n["id"]]
    if unres:
        out.append("  not expanded: " + "; ".join(f"{u['name']} ({u['reason']})" for u in unres[:12]))
    a = (ann or {}).get("nodes", {}).get(n["id"]) if ann else None
    if a:
        bits = []
        if a.get("note"):
            bits.append("note: " + a["note"])
        if a.get("tags"):
            bits.append("tags: " + ", ".join(a["tags"]))
        if a.get("verified_body_hash"):
            bits.append("verified: " + ("unchanged" if a["verified_body_hash"] == n.get("body_hash") else "BODY CHANGED since verification"))
        for pname, pa in (a.get("params") or {}).items():
            if pa.get("dir"):
                bits.append(f"param {pname} dir overridden to {pa['dir']}")
        if bits:
            out.append("  annotations: " + "; ".join(bits))
    return "\n".join(out)


def fmt_type(t: dict, g: dict, depth: int = 0, seen: Optional[set] = None) -> str:
    seen = seen or set()
    unit = "b" if t.get("lang") in ("sv", "vhdl") else ""
    head = f"{t['id']}  [{t['kind']}" + (f", size {t['size']}{unit}" if t.get("size") is not None else "") + (f", align {t['align']}" if t.get("align") else "") + \
        (", system" if t.get("system") else "") + "]"
    out = [("  " * depth) + head]
    if t.get("loc"):
        out.append(("  " * depth) + f"  {t['loc']['file']}:{t['loc']['line']}")
    if t.get("underlying"):
        out.append(("  " * depth) + f"  alias of {t['underlying']}" + (f" -> {t['underlying_ref']}" if t.get("underlying_ref") else ""))
        under = g.get("types", {}).get(t.get("underlying_ref") or "")
        if under and (under.get("fields") or under.get("enumerators")) and depth < 2 and under["id"] not in seen:
            out.append(fmt_type(under, g, depth + 1, seen | {t["id"]}))
    for f in t.get("fields", []):
        pos = ""
        if unit:
            if f.get("bit_offset") is not None and f.get("bit_width") is not None:
                pos = f" [{f['bit_offset'] + f['bit_width'] - 1}:{f['bit_offset']}]"
        else:
            if f.get("offset") is not None:
                pos = f" @{f['offset']}" + (f"+{f['size']}" if f.get("size") is not None else "") + (f" bits {f['bit_offset']}:{f['bit_width']}" if f.get("bit_width") else "")
        out.append(("  " * depth) + f"  .{f['name'] or '(anon)'}: {f['type']}{pos}" + (f" -> {f['type_ref']}" if f.get("type_ref") else ""))
        sub = g.get("types", {}).get(f.get("type_ref") or "")
        if sub and sub.get("fields") and depth < 2 and sub["id"] not in seen:
            out.append(fmt_type(sub, g, depth + 1, seen | {t["id"]}))
    for e in t.get("enumerators", [])[:64]:
        out.append(("  " * depth) + f"  {e['name']} = {e['value']}")
    if t.get("used_by"):
        out.append(("  " * depth) + "  used by: " + ", ".join(_short(x) for x in t["used_by"][:20]))
    return "\n".join(out)


# ---------------------------------------------------------------- server

def build_server(root: str) -> MCPServer:
    root = os.path.abspath(root)
    store = GraphStore(root)
    srv = MCPServer("hx", instructions=(
        "hx holds pre-extracted structure of this project's code: per function the signature, parameters with in/out, "
        "types/structs with offsets, globals touched and call edges, keyed by stable ids like c:src/dma.c::dma_start. "
        "Use search/get_function/callees/callers/get_type instead of reading files; use diff_since to see what changed; "
        "use extract to index a function that is not tracked yet."))

    @srv.tool()
    def list_graphs() -> str:
        """List available graphs (one per tracked entry point) with their entry id, language, size and timestamp."""
        gs = store.available()
        if not gs:
            return "No graphs. Run `hx update` after `hx track <file>:<symbol>`, or call extract(entry)."
        return "\n".join(f"{g['name']:<40} {g['entry']}  [{g['lang']}, {g['nodes']} functions, {g['generated']}]" for g in gs)

    @srv.tool()
    def get_function(id: str, graph: str = "") -> str:
        """Full record of one function/module by stable id (or bare name): signature, params in/out, types, globals, call sites with args, callers, annotations."""
        info, g = store.load(graph)
        n = g["nodes"].get(id)
        if n is None:
            hits = [x for x in g["nodes"].values() if x["name"] == id or x["qualname"] == id or x["id"].endswith("::" + id)]
            if len(hits) == 1:
                n = hits[0]
            elif hits:
                return "ambiguous; candidates:\n" + "\n".join("  " + x["id"] for x in hits)
            else:
                return f"not in graph {info['name']}: {id}. Try search(query) or extract(entry)."
        ann = ann_mod.load(os.path.join(project.hx_dir(root), "annotations.json"))
        return fmt_node(n, g, ann)

    @srv.tool()
    def callees(id: str, depth: int = 1, graph: str = "") -> str:
        """Call tree below a function up to `depth` levels: one line per callee with signature and edge kind."""
        info, g = store.load(graph)
        if id not in g["nodes"]:
            return f"not in graph {info['name']}: {id}"
        out, seen = [], set()
        unres = {(u["from"], u.get("id") or u["name"]): u["reason"] for u in g.get("unresolved", [])}

        def walk(nid, lvl):
            for e in [e for e in g["edges"] if e["from"] == nid]:
                tgt = e.get("to")
                label = _short(tgt) if tgt else f"({e.get('name')})"
                n = g["nodes"].get(tgt) if tgt else None
                line = "  " * lvl + f"{e['kind']:8} {label}" + (f"  `{n['signature']}`" if n else f"  [{unres.get((nid, tgt or e.get('name')), 'not expanded')}]")
                out.append(line)
                if n and lvl + 1 < depth and tgt not in seen:
                    seen.add(tgt)
                    walk(tgt, lvl + 1)
        walk(id, 0)
        return f"{id}\n" + ("\n".join(out) if out else "  (no calls)")

    @srv.tool()
    def callers(id: str, graph: str = "") -> str:
        """Functions that call `id` (direct callers present in the graph), with call-site arguments and locations."""
        info, g = store.load(graph)
        inc = [e for e in g["edges"] if e.get("to") == id]
        if not inc:
            return f"no callers of {id} in graph {info['name']} (extract with include_callers=true to walk upward)"
        return "\n".join(f"{_short(e['from'])}  {e['kind']}({', '.join(e.get('args') or [])})  @{e['loc']['file']}:{e['loc']['line']}" if e.get("loc")
                         else f"{_short(e['from'])}  {e['kind']}" for e in inc)

    @srv.tool()
    def get_type(id: str, graph: str = "") -> str:
        """Struct/union/enum/typedef by id or name: fields with offsets and sizes (bits for HDL), nested types, enumerators, users."""
        info, g = store.load(graph)
        t = g["types"].get(id)
        if t is None:
            hits = [x for x in g["types"].values() if x["name"] == id or x["id"].endswith(id) or x["id"].endswith("::" + id)]
            if len(hits) == 1:
                t = hits[0]
            elif hits:
                return "ambiguous; candidates:\n" + "\n".join("  " + x["id"] for x in hits)
            else:
                return f"type not in graph {info['name']}: {id}"
        return fmt_type(t, g)

    @srv.tool()
    def search(query: str, graph: str = "", kind: str = "") -> str:
        """Find functions, types and globals whose id or name contains `query` (case-insensitive). kind: function|type|global|'' (all)."""
        info, g = store.load(graph)
        q = query.lower()
        out = []
        if kind in ("", "function"):
            out += [f"function {n['id']}  `{n['signature']}`" for n in g["nodes"].values() if q in n["id"].lower() or q in n["signature"].lower()]
        if kind in ("", "type"):
            out += [f"type     {t['id']}  [{t['kind']}{', ' + str(t['size']) + ('b' if t.get('lang') == 'sv' else 'B') if t.get('size') is not None else ''}]" for t in g["types"].values() if q in t["id"].lower()]
        if kind in ("", "global"):
            out += [f"global   {v['id']}  {v['type']}" for v in g.get("globals", {}).values() if q in v["id"].lower()]
        if kind in ("", "function"):
            out += [f"ghost    {u.get('id') or u['name']}  ({u['reason']}, from {_short(u['from'])})" for u in g.get("unresolved", []) if q in (u.get("id") or u["name"]).lower()]
        return "\n".join(out[:60]) + (f"\n… {len(out) - 60} more" if len(out) > 60 else "") if out else f"no match for {query!r} in graph {info['name']}"

    @srv.tool()
    def diff_since(since: str = "prev", graph: str = "") -> str:
        """What changed structurally in a tracked graph since a history point ('prev' = the last snapshot, or a snapshot ts / ISO time). Markdown, ~20 lines."""
        info, g = store.load(graph)
        entry_arg = info.get("entry_arg") or info.get("entry")
        h = project.resolve_history(root, entry_arg, since)
        if not h:
            return f"no history for {info['name']} yet; snapshots are taken by `hx update`/`hx watch` and the viewer's baseline button"
        old = project.load_graph(h["path"])
        d = diff_graphs(old, g)
        return render_markdown(d, g, title=f"{info['name']} since {h['ts']}")

    @srv.tool()
    def extract(entry: str, depth: int = 3, include_callers: bool = False, track: bool = False) -> str:
        """Index `file:function` now (any supported language) and return a summary; the graph becomes queryable by name. track=true also adds it to .hx/config.toml."""
        from .api import extract as do_extract
        t0 = time.time()
        try:
            graph = do_extract(entry, root=root, depth=depth, include_callers=include_callers)
        except Exception as e:  # noqa: BLE001
            return f"extract failed: {type(e).__name__}: {e}"
        gp = project.graph_path(root, entry)
        if os.path.exists(gp):
            project.snapshot(root, entry, gp)
        graph.save(gp)
        if track:
            project.track(root, entry, depth=depth, include_callers=include_callers or None)
        name = project.slug(entry)
        return (f"graph {name}: {graph.entry}  {len(graph.nodes)} functions, {len(graph.types)} types, {len(graph.edges)} edges, "
                f"{len(graph.unresolved)} not expanded ({round(time.time() - t0, 1)}s)\n"
                + "\n".join(f"  d{n['depth']} {n['id']}  `{n['signature']}`" for n in list(graph.to_dict()['nodes'].values())[:25]))

    @srv.tool()
    def annotate(id: str, note: str = "", tags: str = "") -> str:
        """Attach a note and/or comma-separated tags to a function/type id in annotations.json (shared with the viewer). Empty values are left untouched."""
        path = os.path.join(project.hx_dir(root), "annotations.json")
        sym = id.split("::")[-1]
        bucket = "types" if sym.startswith(("struct ", "union ", "enum ", "class ", "anon@")) else "nodes"
        patch: dict = {}
        if note:
            patch["note"] = note
        if tags:
            patch["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        if not patch:
            return "nothing to do"
        doc = ann_mod.patch_file(path, {bucket: {id: patch}})
        return f"annotated {id}: {json.dumps(doc[bucket].get(id), ensure_ascii=False)}"

    return srv
