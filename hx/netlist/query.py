"""Read-only circuit queries over an extracted graph, never over live sources."""
from __future__ import annotations

import json


class QueryError(ValueError):
    pass


def _circuit(graph):
    c = graph.get("circuit")
    if not c:
        raise QueryError("selected graph has no circuit data; extract a netlist first")
    return c


def _select(records, name):
    if name in records:
        return name
    hits = [k for k, r in records.items() if k.lower() == name.lower() or
            str(r.get("spelled", "")).lower() == name.lower()]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise QueryError("ambiguous name; candidates: " + ", ".join(sorted(hits)))
    raise QueryError(f"not in selected circuit: {name}")


def _page(rows, limit):
    if not 1 <= limit <= 1000:
        raise QueryError("limit must be between 1 and 1000")
    return {"results": rows[:limit], "total": len(rows), "truncated": len(rows) > limit}


def boundaries(graph):
    result = {"scope": "selected graph only", "unresolved": len(graph.get("unresolved", [])),
            "extraction": {k: graph.get("meta", {}).get("extract_args", {}).get(k)
                           for k in ("depth", "max_nodes")}}
    if any(n.get("attrs", {}).get("guard_id") and "guard_constraints" not in n["attrs"]
           for n in graph.get("nodes", {}).values()):
        result["guard_context"] = "legacy graph lacks guard constraints; re-extract to filter conditional alternatives"
    return result


def connections(graph):
    c = _circuit(graph)
    out = []
    for table, role in (("terminals", "terminal"), ("ports", "port")):
        for nid, rows in c.get(table, {}).items():
            n = graph.get("nodes", {}).get(nid, {})
            attrs = n.get("attrs", {})
            for r in rows:
                out.append({"node": nid, "kind": role, "terminal": r.get(role),
                            "net": r.get("net") if role == "terminal" else r.get("inner"),
                            "canonical": r.get("canonical", r.get("net")), "outer": r.get("outer"),
                            "as_written": r.get("as_written"), "guard_id": attrs.get("guard_id"),
                            "guard": attrs.get("guard_constraints", []), "loc": n.get("loc")})
    return out


def get_net(graph, net, *, node="", limit=60):
    c = _circuit(graph)
    key = _select(c.get("nets", {}), net)
    rows = connections(graph)
    if node and node not in graph.get("nodes", {}):
        raise QueryError(f"node not in selected graph: {node}")
    direct = [r for r in rows if key in (r["net"], r["canonical"], r["outer"])]
    if node:
        direct = [r for r in direct if r["node"] == node]
        if not direct:
            raise QueryError(f"net {key} is not connected to node {node}")
    canonical = {r["canonical"] for r in direct}
    if not node:
        canonical.update(b["canonical"] for b in c["nets"][key].get("bindings", []) if b.get("canonical"))
    canonical = canonical or {key}
    selected_guard = {g["chain"]: g["branch"] for g in graph.get("nodes", {}).get(node, {}).get("attrs", {}).get("guard_constraints", [])}
    matched = [r for r in rows if r["canonical"] in canonical and
               all(g["chain"] not in selected_guard or selected_guard[g["chain"]] == g["branch"] for g in r["guard"])]
    matched.sort(key=lambda r: (r["canonical"], r["node"], r["kind"], r["terminal"] or ""))
    aliases = sorted({r["net"] for r in matched if r["net"]} | canonical)
    return {"key": key, "kind": "net", "record": c["nets"][key], "canonical": sorted(canonical),
            "aliases": aliases, "context": node or None, **_page(matched, limit), "boundaries": boundaries(graph)}


def uses(graph, target, *, kind, limit=60):
    c = _circuit(graph)
    if kind not in ("definition", "model"):
        raise QueryError("kind must be definition or model")
    records = c.get("definitions" if kind == "definition" else "models", {})
    key = _select(records, target)
    record = records[key]
    ghosts = {u.get("id"): u for u in graph.get("unresolved", []) if u.get("id")}
    rows = []
    for nid in sorted(set(record.get("instances" if kind == "definition" else "used_by", []))):
        n = graph.get("nodes", {}).get(nid)
        u = ghosts.get(nid, {})
        rows.append({"node": nid, "name": n.get("name") if n else u.get("name", nid),
                     "loc": n.get("loc") if n else u.get("loc"), "expanded": n is not None,
                     "reason": None if n else u.get("reason", "not expanded in selected graph")})
    return {"key": key, "kind": kind, "record": record, **_page(rows, limit), "boundaries": boundaries(graph)}


def format_result(result):
    """Compact text shared by CLI and MCP; JSON preserves all declaration metadata."""
    lines = [f"{result['kind']} {result['key']} ({result['total']} connections/users; selected graph only)"]
    record = result.get("record", {})
    if record.get("status"):
        lines.append("status: " + record["status"])
    if result["boundaries"].get("guard_context"):
        lines.append(result["boundaries"]["guard_context"])
    if "canonical" in result:
        lines.append("canonical: " + ", ".join(result["canonical"]))
        lines.append("aliases: " + ", ".join(result["aliases"]))
    for d in record.get("declarations", []):
        lines.append(f"decl {d.get('identity', '')} {d.get('file')}:{d.get('line')}" +
                     (" guard=" + json.dumps(d["guard"]) if d.get("guard") else ""))
    for r in result["results"]:
        lines.append(f"  {r['node']}" + (f" {r['terminal']} -> {r['canonical']}" if "terminal" in r else "") +
                     (f" [guard {r['guard_id']}]" if r.get("guard_id") else "") +
                     (f" ({r['reason']})" if r.get("reason") else ""))
    if result["truncated"]:
        lines.append(f"… {result['total'] - len(result['results'])} more")
    return "\n".join(lines)
