"""Structural diff between two graph.json documents.

The point of hx: after an agent session you read this (~20 lines of Markdown)
instead of the agent's narration. The JSON form drives the viewer's diff mode.
Identity is the stable id; edges are keyed by (from, to-or-fnptr-name, kind,
macro) so line-number drift does not register as change.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

from . import values as _values

SCHEMA = "hx-diff/1"


def _short(i: Optional[str]) -> str:
    if not i:
        return "?"
    return i.split(":", 1)[1] if ":" in i and "::" in i else i


def _leaf(i: Optional[str]) -> str:
    """Symbol part of an id: everything after the first '::' (C++ ids contain further '::' and parameter lists)."""
    if not i:
        return "?"
    return i.split("::", 1)[1] if "::" in i else i


def _diff_attrs(a: dict, b: dict) -> dict:
    """Frontend extras (SV parameters/signals, Rust module path, …) compared key-wise; lists of named dicts as
    added/removed names, everything else by JSON equality."""
    out: dict[str, Any] = {}
    for k in sorted(set(a) | set(b)):
        va, vb = a.get(k), b.get(k)
        if va == vb:
            continue
        if isinstance(va, dict) and isinstance(vb, dict) and not (va and all(isinstance(x, dict) for x in va.values())):
            for kk in sorted(set(va) | set(vb)):
                x, y = va.get(kk), vb.get(kk)
                if x != y and not (k == "parameters" and kk in va and kk in vb and _values.equal(x, y)):
                    out[f"{k}.{kk}"] = {"old": x, "new": y}
        elif isinstance(va, list) and isinstance(vb, list) and all(isinstance(x, dict) and "name" in x for x in va + vb):
            na, nb = {x["name"]: x for x in va}, {x["name"]: x for x in vb}
            d = {"added": sorted(set(nb) - set(na)), "removed": sorted(set(na) - set(nb)),
                 "changed": sorted(n for n in set(na) & set(nb) if na[n] != nb[n])}
            out[k] = {kk: vv for kk, vv in d.items() if vv}
        else:
            out[k] = {"old": va, "new": vb}
    return out


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


_PARAM_VALUE = re.compile(r"(\w+)=[^,()]*(?:\([^()]*\))?")


def _sig_shape(n: dict) -> Optional[str]:
    """Signature text compared across graphs. Nodes that carry `attrs.parameters` (SV modules/instances) have their
    parameter VALUES reduced to placeholders: values are compared numerically through `values.equal` in
    `_diff_attrs`, so a legacy decimal and a new hex rendering of one value never register as a signature change
    while a renamed port, an added/removed parameter or a genuinely different value still does."""
    sig = n.get("signature")
    if not sig or not isinstance((n.get("attrs") or {}).get("parameters"), dict):
        return sig
    i, j = sig.find("#("), sig.find(")", sig.find("#(") + 2) if "#(" in sig else (-1, -1)
    if i < 0 or j < 0:
        return sig
    # the parameter list may contain nested parentheses; find its matching close
    depth, k = 0, i + 1
    while k < len(sig):
        if sig[k] == "(":
            depth += 1
        elif sig[k] == ")":
            depth -= 1
            if depth == 0:
                break
        k += 1
    inner = sig[i + 2:k]
    names = [seg.split("=", 1)[0].strip() for seg in _split_top(inner)]
    return sig[:i] + "#(" + ", ".join(f"{nm}=…" for nm in names) + sig[k + 1:]


def _split_top(text: str) -> list[str]:
    out, depth, cur = [], 0, []
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur or out:
        out.append("".join(cur))
    return [x for x in out if x.strip()]


def _edge_key(e: dict) -> tuple:
    return (e["from"], e.get("to") or f"fnptr:{e.get('name')}", e["kind"], e.get("macro") or "")


def diff_graphs(old: dict, new: dict) -> dict:
    """Compare two graph dictionaries and return an hx-diff/1 document.

    Args:
        old: Baseline graph, preferably from the shared graph loader or Graph.to_dict.
        new: Current graph with the same intended build configuration.

    Returns:
        Category-specific changes and a summary whose any flag indicates differences.
        Input files and annotations are not modified. This function does not upgrade
        schemas; load legacy graph files through the shared readers first.
    """
    on, nn = old.get("nodes", {}), new.get("nodes", {})
    ot, nt = old.get("types", {}), new.get("types", {})
    og, ng = old.get("globals", {}), new.get("globals", {})

    nodes_added = sorted(set(nn) - set(on))
    nodes_removed = sorted(set(on) - set(nn))
    nodes_changed: dict[str, dict] = {}
    for nid in sorted(set(on) & set(nn)):
        a, b = on[nid], nn[nid]
        ch: dict[str, Any] = {}
        if _sig_shape(a) != _sig_shape(b):
            ch["signature"] = {"old": a.get("signature"), "new": b.get("signature")}
        pd = _diff_params(a.get("params", []), b.get("params", []))   # always: a dir flip need not change the text
        if pd:
            ch["params"] = pd
        ad = _diff_attrs(a.get("attrs") or {}, b.get("attrs") or {})
        if ad:
            ch["attrs"] = ad
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
    pairs = _pair_relayouts(types_removed, types_added, ot, nt)       # layout-identified types edited in place
    types_removed = [t for t in types_removed if t not in pairs]
    types_added = [t for t in types_added if t not in pairs.values()]
    for old_id, new_id in pairs.items():
        a, b = ot[old_id], nt[new_id]
        ch = {"renamed": {"old": old_id, "new": new_id}}
        for attr in ("size", "align", "kind", "underlying"):
            if a.get(attr) != b.get(attr):
                ch[attr] = {"old": a.get(attr), "new": b.get(attr)}
        fd = _diff_fields(a.get("fields", []), b.get("fields", []))
        if fd:
            ch["fields"] = fd
        types_changed[new_id] = ch
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
        ed += [{"name": k, "change": "value", "old": ea[k], "new": eb[k]} for k in eb if k in ea and not _values.equal(ea[k], eb[k])]
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
            gone, came = ca - cb, cb - ca            # argument tuples that changed, independent of the count delta
            if gone and came:
                edges_args.append({**_edge_view(k, 0), "old_args": [list(x) for x in gone.elements()], "new_args": [list(x) for x in came.elements()]})

    circuit = _diff_circuit(old.get("circuit"), new.get("circuit"), nodes_changed, set(on) & set(nn))

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
        "wiring_changed": circuit["wiring_changed"], "models_changed": circuit["models_changed"],
        "cdefs_changed": circuit["cdefs_changed"], "cparams_changed": circuit["cparams_changed"],
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
        "circuit": circuit["sections"],
    }


def _decl_hashes(rec: dict) -> dict[str, dict]:
    """declaration identity (`scope/name#<guard_id>`) -> declaration record, for one circuit declaration entry."""
    return {(d.get("identity") or ""): d for d in rec.get("declarations", [])}


def _diff_decls(a: dict, b: dict) -> dict:
    """Netlist declarations (models, definitions, params) compared by their guarded identity: an edited `.model`
    card registers even when every instance keeps its model name; an edit confined to one branch moves one key."""
    da = {ident: d for rec in a.values() for ident, d in _decl_hashes(rec).items()}
    db = {ident: d for rec in b.values() for ident, d in _decl_hashes(rec).items()}
    changed = [{"key": k, "old_hash": da[k].get("hash"), "new_hash": db[k].get("hash")} for k in sorted(set(da) & set(db)) if da[k].get("hash") != db[k].get("hash")]
    out = {"added": sorted(set(db) - set(da)), "removed": sorted(set(da) - set(db)), "changed": changed}
    return {k: v for k, v in out.items() if v}


def _diff_circuit(oc: Optional[dict], nc: Optional[dict], nodes_changed: dict, common_nodes: set) -> dict:
    """Terminal→net rewiring per common node plus declaration-level changes of the netlist block."""
    out = {"wiring_changed": 0, "models_changed": 0, "cdefs_changed": 0, "cparams_changed": 0, "sections": {}}
    if not oc and not nc:
        return out
    oc, nc = oc or {}, nc or {}
    # Immediate bindings only: a device's terminal net keys in its scope, an instance's `outer` nets (the ones written
    # on its line, in the parent's scope). Canonical nets would report an ancestor's rewiring on every descendant.
    ot, nt = oc.get("terminals", {}), nc.get("terminals", {})
    op, np_ = oc.get("ports", {}), nc.get("ports", {})
    for nid in sorted(common_nodes):
        a = {t["terminal"]: t["net"] for t in ot.get(nid, [])} or {t["port"]: t["outer"] for t in op.get(nid, [])}
        b = {t["terminal"]: t["net"] for t in nt.get(nid, [])} or {t["port"]: t["outer"] for t in np_.get(nid, [])}
        w = [{"terminal": t, "old": a.get(t), "new": b.get(t)} for t in list(a) + [t for t in b if t not in a] if a.get(t) != b.get(t)]
        if w:
            nodes_changed.setdefault(nid, {})["wiring"] = w
            out["wiring_changed"] += 1
    sections = {}
    for key, name in (("models", "models"), ("definitions", "definitions"), ("params", "params")):
        d = _diff_decls(oc.get(key, {}), nc.get(key, {}))
        if d:
            sections[name] = d
            out[{"models": "models_changed", "definitions": "cdefs_changed", "params": "cparams_changed"}[key]] = sum(len(v) for v in d.values())
    out["sections"] = sections
    return out


_LAYOUT_SUFFIX = re.compile(r"@[0-9a-f]{8}$")


def _pair_relayouts(removed: list, added: list, ot: dict, nt: dict) -> dict:
    """Pair a removed with an added type when they share the base id (the `@fingerprint` suffix stripped) AND
    their `used_by` sets intersect: instance ids are stable hierarchy paths, so the users identify the
    specialization. Ambiguous (several candidates either way) -> left as removed/added."""
    base = lambda t: _LAYOUT_SUFFIX.sub("", t)
    by_base: dict[str, list] = {}
    for t in added:
        by_base.setdefault(base(t), []).append(t)
    pairs: dict = {}
    taken: set = set()
    for r in removed:
        cands = [a for a in by_base.get(base(r), []) if a not in taken and set(ot[r].get("used_by") or []) & set(nt[a].get("used_by") or [])]
        rivals = [x for x in removed if x != r and base(x) == base(r) and any(set(ot[x].get("used_by") or []) & set(nt[a].get("used_by") or []) for a in cands)]
        if len(cands) == 1 and not rivals:
            pairs[r] = cands[0]
            taken.add(cands[0])
    return pairs


def _edge_view(k: tuple, count: int) -> dict:
    return {"from": k[0], "to": k[1], "kind": k[2], "macro": k[3] or None, "count": count}


# ---------------------------------------------------------------- markdown

def _cap(items: list, limit: int) -> tuple[list, int]:
    return items[:limit], max(0, len(items) - limit)


def render_markdown(d: dict, new_graph: Optional[dict] = None, limit: int = 12, title: Optional[str] = None) -> str:
    """Render a structural diff as a compact Markdown report.

    Args:
        d: Diff returned by diff_graphs.
        new_graph: Optional current graph for names and change details.
        limit: Maximum displayed items per change section; JSON data stays complete.
        title: Optional report heading.

    Returns:
        Markdown text, without writing files.
    """
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
    if s.get("wiring_changed") or s.get("models_changed") or s.get("cdefs_changed") or s.get("cparams_changed"):
        bits.append(f"circuit wiring~{s.get('wiring_changed', 0)} models~{s.get('models_changed', 0)} defs~{s.get('cdefs_changed', 0)} params~{s.get('cparams_changed', 0)}")
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
            if "returns" in ch and "signature" not in ch:
                parts.append(f"returns {ch['returns']['old']} → {ch['returns']['new']}")
            for k, v in list(ch.get("attrs", {}).items())[:6]:
                if "old" in v or "new" in v:
                    parts.append(f"attr {k} {v.get('old')} → {v.get('new')}")
                else:
                    parts.append(f"attr {k}" + "".join(f" {sign}{', '.join(v[w])}" for sign, w in (("+", "added"), ("−", "removed"), ("~", "changed")) if v.get(w)))
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
                    parts.append(f"calls +{', '.join(_leaf(x) for x in ch['calls']['added'])}")
                if ch["calls"]["removed"]:
                    parts.append(f"calls −{', '.join(_leaf(x) for x in ch['calls']['removed'])}")
            for w in ch.get("wiring", [])[:6]:
                parts.append(f"wiring {w['terminal']} {w['old']} → {w['new']}")
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
            if "renamed" in ch:
                parts.append("layout changed (id " + _leaf(ch["renamed"]["old"]).rsplit("@", 1)[-1] + " → " + _leaf(ch["renamed"]["new"]).rsplit("@", 1)[-1] + ")")
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
            lines.append(f"+ {_leaf(e['from'])} → {_leaf(e['to']) if not e['to'].startswith('fnptr:') else e['to']} ({e['kind']}{'×' + str(e['count']) if e['count'] > 1 else ''})")
        if more:
            lines.append(f"  … {more} more added")
        items, more = _cap(d["edges"]["removed"], limit)
        for e in items:
            lines.append(f"− {_leaf(e['from'])} → {_leaf(e['to']) if not e['to'].startswith('fnptr:') else e['to']} ({e['kind']}{'×' + str(e['count']) if e['count'] > 1 else ''})")
        if more:
            lines.append(f"  … {more} more removed")
        for e in d["edges"]["args_changed"][:limit]:
            lines.append(f"~ {_leaf(e['from'])} → {_leaf(e['to'])} args {e['old_args']} → {e['new_args']}")

    if d.get("circuit"):
        lines.append("")
        lines.append("## Circuit")
        for name, dd in d["circuit"].items():
            for k in dd.get("added", [])[:limit]:
                lines.append(f"+ {name[:-1] if name.endswith('s') else name} {k}")
            for k in dd.get("removed", [])[:limit]:
                lines.append(f"− {name[:-1] if name.endswith('s') else name} {k}")
            for c in dd.get("changed", [])[:limit]:
                lines.append(f"~ {name[:-1] if name.endswith('s') else name} {c['key']}  ({(c['old_hash'] or '?')[:12]} → {(c['new_hash'] or '?')[:12]})")

    if d["unresolved"]["added"] or d["unresolved"]["removed"]:
        lines.append("")
        lines.append("## Unresolved")
        for u in d["unresolved"]["added"][:limit]:
            lines.append(f"+ {u['name']}  ({u['reason']}) from {_leaf(u['from'])}")
        for u in d["unresolved"]["removed"][:limit]:
            lines.append(f"− {u['name']}  ({u['reason']}) from {_leaf(u['from'])}")
    return "\n".join(lines) + "\n"
