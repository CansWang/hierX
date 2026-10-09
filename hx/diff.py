"""Structural diff between two graph.json documents.

The point of hx: after an agent session you read this (~20 lines of Markdown)
instead of the agent's narration. The JSON form drives the viewer's diff mode.
Identity is the stable id; edges are keyed by (from, to-or-fnptr-name, kind,
macro) so line-number drift does not register as change.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Optional

SCHEMA = "hx-diff/1"


def _short(i: Optional[str]) -> str:
    if not i:
        return "?"
    return i.split(":", 1)[1] if ":" in i and "::" in i else i


def _loc_lines(n: dict) -> Optional[int]:
    loc = n.get("loc") or {}
    if loc.get("end_line") and loc.get("line"):
        return loc["end_line"] - loc["line"] + 1
    return None


def _list_diff(a: list, b: list) -> dict:
    sa, sb = set(a or []), set(b or [])
    return {"added": sorted(sb - sa), "removed": sorted(sa - sb)}


def _diff_params(old: list[dict], new: list[dict]) -> list[dict]:
    on = {p["name"]: p for p in old}
    nn = {p["name"]: p for p in new}
    out = []
    for name in [p["name"] for p in old if p["name"] not in nn]:
        out.append({"name": name, "change": "removed", "old": {"type": on[name]["type"], "dir": on[name]["dir"]}})
    for name in [p["name"] for p in new if p["name"] not in on]:
        out.append({"name": name, "change": "added", "new": {"type": nn[name]["type"], "dir": nn[name]["dir"]}})
    for name in [p["name"] for p in new if p["name"] in on]:
        a, b = on[name], nn[name]
        if a["type"] != b["type"]:
            out.append({"name": name, "change": "type", "old": a["type"], "new": b["type"]})
        if a["dir"] != b["dir"]:
            out.append({"name": name, "change": "dir", "old": a["dir"], "new": b["dir"]})
    if [p["name"] for p in old if p["name"] in nn] != [p["name"] for p in new if p["name"] in on]:
        out.append({"name": "", "change": "reordered", "old": [p["name"] for p in old], "new": [p["name"] for p in new]})
    return out


def _diff_fields(old: list[dict], new: list[dict]) -> list[dict]:
    def key(f, i):
        return f.get("name") or f"(anon#{i})"
    on = {key(f, i): f for i, f in enumerate(old)}
    nn = {key(f, i): f for i, f in enumerate(new)}
    out = []
    for k in on:
        if k not in nn:
            out.append({"name": k, "change": "removed", "old": _field_view(on[k])})
    for k in nn:
        if k not in on:
            out.append({"name": k, "change": "added", "new": _field_view(nn[k])})
    for k in nn:
        if k not in on:
            continue
        a, b = on[k], nn[k]
        for attr in ("type", "offset", "size", "bit_offset", "bit_width"):
            if a.get(attr) != b.get(attr):
                out.append({"name": k, "change": attr, "old": a.get(attr), "new": b.get(attr)})
    if [key(f, i) for i, f in enumerate(old) if key(f, i) in nn] != [key(f, i) for i, f in enumerate(new) if key(f, i) in on]:
        out.append({"name": "", "change": "reordered", "old": list(on), "new": list(nn)})
    return out


def _field_view(f: dict) -> dict:
    return {k: f.get(k) for k in ("type", "offset", "size", "bit_offset", "bit_width") if f.get(k) is not None}


def _edge_key(e: dict) -> tuple:
    return (e["from"], e.get("to") or f"fnptr:{e.get('name')}", e["kind"], e.get("macro") or "")


def diff_graphs(old: dict, new: dict) -> dict:
    on, nn = old.get("nodes", {}), new.get("nodes", {})
    ot, nt = old.get("types", {}), new.get("types", {})
    og, ng = old.get("globals", {}), new.get("globals", {})

    nodes_added = sorted(set(nn) - set(on))
    nodes_removed = sorted(set(on) - set(nn))
    nodes_changed: dict[str, dict] = {}
    for nid in sorted(set(on) & set(nn)):
        a, b = on[nid], nn[nid]
        ch: dict[str, Any] = {}
        if a.get("signature") != b.get("signature"):
            ch["signature"] = {"old": a.get("signature"), "new": b.get("signature")}
            pd = _diff_params(a.get("params", []), b.get("params", []))
            if pd:
                ch["params"] = pd
        ra, rb = (a.get("returns") or {}).get("type"), (b.get("returns") or {}).get("type")
        if ra != rb:
            ch["returns"] = {"old": ra, "new": rb}
        if a.get("body_hash") != b.get("body_hash"):
            la, lb = _loc_lines(a), _loc_lines(b)
            ch["body"] = {"old_hash": a.get("body_hash"), "new_hash": b.get("body_hash"),
                          "old_lines": la, "new_lines": lb, "loc_delta": (lb - la) if la is not None and lb is not None else None}
        gl = {}
        for what in ("reads", "writes"):
            d = _list_diff((a.get("globals") or {}).get(what, []), (b.get("globals") or {}).get(what, []))
            if d["added"] or d["removed"]:
                gl[what] = d
        if gl:
            ch["globals"] = gl
        cd = _list_diff(a.get("calls", []), b.get("calls", []))
        if cd["added"] or cd["removed"]:
            ch["calls"] = cd
        if a.get("depth") != b.get("depth"):
            ch["depth"] = {"old": a.get("depth"), "new": b.get("depth")}
        if (a.get("loc") or {}).get("file") != (b.get("loc") or {}).get("file"):
            ch["moved"] = {"old": (a.get("loc") or {}).get("file"), "new": (b.get("loc") or {}).get("file")}
        if a.get("storage") != b.get("storage"):
            ch["storage"] = {"old": a.get("storage"), "new": b.get("storage")}
        if ch:
            nodes_changed[nid] = ch

    types_added = sorted(set(nt) - set(ot))
    types_removed = sorted(set(ot) - set(nt))
    types_changed: dict[str, dict] = {}
    for tid in sorted(set(ot) & set(nt)):
        a, b = ot[tid], nt[tid]
        ch = {}
        for attr in ("size", "align", "kind", "underlying", "underlying_ref"):
            if a.get(attr) != b.get(attr):
                ch[attr] = {"old": a.get(attr), "new": b.get(attr)}
        fd = _diff_fields(a.get("fields", []), b.get("fields", []))
        if fd:
            ch["fields"] = fd
        ea = {e["name"]: e["value"] for e in a.get("enumerators", [])}
        eb = {e["name"]: e["value"] for e in b.get("enumerators", [])}
        ed = [{"name": k, "change": "removed", "old": ea[k]} for k in ea if k not in eb]
        ed += [{"name": k, "change": "added", "new": eb[k]} for k in eb if k not in ea]
        ed += [{"name": k, "change": "value", "old": ea[k], "new": eb[k]} for k in eb if k in ea and ea[k] != eb[k]]
        if ed:
            ch["enumerators"] = ed
        if ch:
            types_changed[tid] = ch

    globals_added = sorted(set(ng) - set(og))
    globals_removed = sorted(set(og) - set(ng))
    globals_changed = {}
    for gid in sorted(set(og) & set(ng)):
        a, b = og[gid], ng[gid]
        ch = {attr: {"old": a.get(attr), "new": b.get(attr)} for attr in ("type", "storage", "scope") if a.get(attr) != b.get(attr)}
        if ch:
            globals_changed[gid] = ch

    oe: dict[tuple, list] = {}
    ne: dict[tuple, list] = {}
    for e in old.get("edges", []):
        oe.setdefault(_edge_key(e), []).append(tuple(e.get("args") or []))
    for e in new.get("edges", []):
        ne.setdefault(_edge_key(e), []).append(tuple(e.get("args") or []))
    edges_added, edges_removed, edges_args = [], [], []
    for k in sorted(set(oe) | set(ne), key=str):
        ca, cb = Counter(oe.get(k, [])), Counter(ne.get(k, []))
        if k not in oe:
            edges_added.append(_edge_view(k, sum(cb.values())))
        elif k not in ne:
            edges_removed.append(_edge_view(k, sum(ca.values())))
        else:
            if sum(ca.values()) > sum(cb.values()):
                edges_removed.append(_edge_view(k, sum(ca.values()) - sum(cb.values())))
            elif sum(cb.values()) > sum(ca.values()):
                edges_added.append(_edge_view(k, sum(cb.values()) - sum(ca.values())))
            if ca != cb and sum(ca.values()) == sum(cb.values()):
                edges_args.append({**_edge_view(k, 0), "old_args": [list(x) for x in ca.elements()], "new_args": [list(x) for x in cb.elements()]})

    ou = {(u["name"], u["from"], u["reason"]) for u in old.get("unresolved", [])}
    nu = {(u["name"], u["from"], u["reason"]) for u in new.get("unresolved", [])}
    unresolved_added = [{"name": n, "from": f, "reason": r} for (n, f, r) in sorted(nu - ou)]
    unresolved_removed = [{"name": n, "from": f, "reason": r} for (n, f, r) in sorted(ou - nu)]

    removed_info = {nid: {"name": on[nid].get("name"), "signature": on[nid].get("signature"), "loc": on[nid].get("loc"),
                          "calls": on[nid].get("calls", []), "depth": on[nid].get("depth")} for nid in nodes_removed}
    summary = {
        "nodes_added": len(nodes_added), "nodes_removed": len(nodes_removed), "nodes_changed": len(nodes_changed),
        "signature_changed": sum(1 for c in nodes_changed.values() if "signature" in c or "returns" in c),
        "body_changed": sum(1 for c in nodes_changed.values() if "body" in c),
        "types_added": len(types_added), "types_removed": len(types_removed), "types_changed": len(types_changed),
        "globals_added": len(globals_added), "globals_removed": len(globals_removed), "globals_changed": len(globals_changed),
        "edges_added": sum(e["count"] for e in edges_added), "edges_removed": sum(e["count"] for e in edges_removed),
        "edges_args_changed": len(edges_args),
        "unresolved_added": len(unresolved_added), "unresolved_removed": len(unresolved_removed),
    }
    summary["total"] = sum(v for k, v in summary.items() if k not in ("nodes_changed",)) + summary["nodes_changed"] - summary["signature_changed"] - summary["body_changed"]
    summary["any"] = any(v for k, v in summary.items() if k not in ("total", "any"))
    return {
        "schema": SCHEMA,
        "old": {"generated": old.get("generated"), "entry": old.get("entry"), "nodes": len(on)},
        "new": {"generated": new.get("generated"), "entry": new.get("entry"), "nodes": len(nn)},
        "summary": summary,
        "nodes": {"added": nodes_added, "removed": nodes_removed, "changed": nodes_changed, "removed_info": removed_info},
        "types": {"added": types_added, "removed": types_removed, "changed": types_changed},
        "globals": {"added": globals_added, "removed": globals_removed, "changed": globals_changed},
        "edges": {"added": edges_added, "removed": edges_removed, "args_changed": edges_args},
        "unresolved": {"added": unresolved_added, "removed": unresolved_removed},
    }


def _edge_view(k: tuple, count: int) -> dict:
    return {"from": k[0], "to": k[1], "kind": k[2], "macro": k[3] or None, "count": count}


# ---------------------------------------------------------------- markdown

def _cap(items: list, limit: int) -> tuple[list, int]:
    return items[:limit], max(0, len(items) - limit)


def render_markdown(d: dict, new_graph: Optional[dict] = None, limit: int = 12, title: Optional[str] = None) -> str:
    s = d["summary"]
    lines: list[str] = []
    head = title or f"hx diff · {d['new'].get('entry') or '?'}"
    lines.append(f"# {head}")
    og, ng = (d["old"].get("generated") or "?")[:16], (d["new"].get("generated") or "?")[:16]
    bits = [f"{og} → {ng}", f"nodes {d['old'].get('nodes')}→{d['new'].get('nodes')}"]
    if s["nodes_added"] or s["nodes_removed"] or s["nodes_changed"]:
        bits.append(f"functions +{s['nodes_added']} −{s['nodes_removed']} ~{s['nodes_changed']}")
    if s["types_added"] or s["types_removed"] or s["types_changed"]:
        bits.append(f"types +{s['types_added']} −{s['types_removed']} ~{s['types_changed']}")
    if s["edges_added"] or s["edges_removed"] or s["edges_args_changed"]:
        bits.append(f"edges +{s['edges_added']} −{s['edges_removed']}" + (f" args~{s['edges_args_changed']}" if s["edges_args_changed"] else ""))
    if s["unresolved_added"] or s["unresolved_removed"]:
        bits.append(f"unresolved +{s['unresolved_added']} −{s['unresolved_removed']}")
    lines.append(" · ".join(bits))
    if not s["any"]:
        lines.append("")
        lines.append("No structural changes.")
        return "\n".join(lines) + "\n"
    nodes = (new_graph or {}).get("nodes", {})

    if d["nodes"]["added"] or d["nodes"]["removed"] or d["nodes"]["changed"]:
        lines.append("")
        lines.append("## Functions")
        items, more = _cap(d["nodes"]["added"], limit)
        for nid in items:
            sig = nodes.get(nid, {}).get("signature", "")
            lines.append(f"+ {_short(nid)}" + (f"  `{sig}`" if sig else ""))
        if more:
            lines.append(f"  … {more} more added")
        items, more = _cap(d["nodes"]["removed"], limit)
        for nid in items:
            sig = d["nodes"]["removed_info"].get(nid, {}).get("signature", "")
            lines.append(f"− {_short(nid)}" + (f"  `{sig}`" if sig else ""))
        if more:
            lines.append(f"  … {more} more removed")
        items, more = _cap(list(d["nodes"]["changed"].items()), limit)
        for nid, ch in items:
            parts = []
            if "signature" in ch:
                parts.append(f"signature `{ch['signature']['old']}` → `{ch['signature']['new']}`")
                for p in ch.get("params", []):
                    if p["change"] == "added":
                        parts.append(f"+param {p['name']}: {p['new']['type']} ({p['new']['dir']})")
                    elif p["change"] == "removed":
                        parts.append(f"−param {p['name']}")
                    elif p["change"] in ("type", "dir"):
                        parts.append(f"param {p['name']} {p['change']} {p['old']} → {p['new']}")
                    elif p["change"] == "reordered":
                        parts.append("params reordered")
            elif "returns" in ch:
                parts.append(f"returns {ch['returns']['old']} → {ch['returns']['new']}")
            if "body" in ch:
                delta = ch["body"].get("loc_delta")
                parts.append("body changed" + (f" ({delta:+d} lines)" if delta is not None else ""))
            if "globals" in ch:
                for what, dd in ch["globals"].items():
                    if dd["added"]:
                        parts.append(f"{what} +{', '.join(_short(x) for x in dd['added'])}")
                    if dd["removed"]:
                        parts.append(f"{what} −{', '.join(_short(x) for x in dd['removed'])}")
            if "calls" in ch:
                if ch["calls"]["added"]:
                    parts.append(f"calls +{', '.join(_short(x).split('::')[-1] for x in ch['calls']['added'])}")
                if ch["calls"]["removed"]:
                    parts.append(f"calls −{', '.join(_short(x).split('::')[-1] for x in ch['calls']['removed'])}")
            if "moved" in ch:
                parts.append(f"moved {ch['moved']['old']} → {ch['moved']['new']}")
            if "storage" in ch:
                parts.append(f"storage {ch['storage']['old']} → {ch['storage']['new']}")
            if "depth" in ch and len(parts) == 0:
                parts.append(f"depth {ch['depth']['old']} → {ch['depth']['new']}")
            if parts:
                lines.append(f"~ {_short(nid)}  " + "; ".join(parts))
        if more:
            lines.append(f"  … {more} more changed")

    if d["types"]["added"] or d["types"]["removed"] or d["types"]["changed"]:
        lines.append("")
        lines.append("## Types")
        types_new = (new_graph or {}).get("types", {})
        added_sys = [t for t in d["types"]["added"] if types_new.get(t, {}).get("system")]
        for tid in [t for t in d["types"]["added"] if t not in added_sys][:limit]:
            lines.append(f"+ {_short(tid)}")
        if added_sys:
            lines.append(f"+ {len(added_sys)} system type(s): " + ", ".join(_short(t).split("::")[-1] for t in added_sys[:6]) + (" …" if len(added_sys) > 6 else ""))
        for tid in d["types"]["removed"][:limit]:
            lines.append(f"− {_short(tid)}")
        items, more = _cap(list(d["types"]["changed"].items()), limit)
        for tid, ch in items:
            parts = []
            for attr in ("size", "align", "kind", "underlying"):
                if attr in ch:
                    parts.append(f"{attr} {ch[attr]['old']} → {ch[attr]['new']}")
            for f in ch.get("fields", [])[:8]:
                if f["change"] == "added":
                    v = f["new"]
                    where = f"@{v['offset']}" if v.get("offset") is not None else (f"@bit{v['bit_offset']}" if v.get("bit_offset") is not None else "")
                    parts.append(f"+field {f['name']}: {v.get('type', '?')}{where}")
                elif f["change"] == "removed":
                    parts.append(f"−field {f['name']}")
                elif f["change"] == "reordered":
                    parts.append("fields reordered")
                else:
                    parts.append(f"field {f['name']} {f['change']} {f['old']} → {f['new']}")
            for e in ch.get("enumerators", [])[:6]:
                if e["change"] == "added":
                    parts.append(f"+enum {e['name']}={e['new']}")
                elif e["change"] == "removed":
                    parts.append(f"−enum {e['name']}")
                else:
                    parts.append(f"enum {e['name']} {e['old']} → {e['new']}")
            lines.append(f"~ {_short(tid)}  " + "; ".join(parts))
        if more:
            lines.append(f"  … {more} more changed")

    if d["globals"]["added"] or d["globals"]["removed"] or d["globals"]["changed"]:
        lines.append("")
        lines.append("## Globals")
        for gid in d["globals"]["added"][:limit]:
            lines.append(f"+ {_short(gid)}")
        for gid in d["globals"]["removed"][:limit]:
            lines.append(f"− {_short(gid)}")
        for gid, ch in list(d["globals"]["changed"].items())[:limit]:
            lines.append(f"~ {_short(gid)}  " + "; ".join(f"{k} {v['old']} → {v['new']}" for k, v in ch.items()))

    if d["edges"]["added"] or d["edges"]["removed"] or d["edges"]["args_changed"]:
        lines.append("")
        lines.append("## Edges")
        items, more = _cap(d["edges"]["added"], limit)
        for e in items:
            lines.append(f"+ {_short(e['from']).split('::')[-1]} → {_short(e['to']).split('::')[-1] if not e['to'].startswith('fnptr:') else e['to']} ({e['kind']}{'×' + str(e['count']) if e['count'] > 1 else ''})")
        if more:
            lines.append(f"  … {more} more added")
        items, more = _cap(d["edges"]["removed"], limit)
        for e in items:
            lines.append(f"− {_short(e['from']).split('::')[-1]} → {_short(e['to']).split('::')[-1] if not e['to'].startswith('fnptr:') else e['to']} ({e['kind']}{'×' + str(e['count']) if e['count'] > 1 else ''})")
        if more:
            lines.append(f"  … {more} more removed")
        for e in d["edges"]["args_changed"][:limit]:
            lines.append(f"~ {_short(e['from']).split('::')[-1]} → {_short(e['to']).split('::')[-1]} args {e['old_args']} → {e['new_args']}")

    if d["unresolved"]["added"] or d["unresolved"]["removed"]:
        lines.append("")
        lines.append("## Unresolved")
        for u in d["unresolved"]["added"][:limit]:
            lines.append(f"+ {u['name']}  ({u['reason']}) from {_short(u['from']).split('::')[-1]}")
        for u in d["unresolved"]["removed"][:limit]:
            lines.append(f"− {u['name']}  ({u['reason']}) from {_short(u['from']).split('::')[-1]}")
    return "\n".join(lines) + "\n"
