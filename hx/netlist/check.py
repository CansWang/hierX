"""`hx netlist check`: extract a deck and cross-check its structure with an optional simulator oracle."""
from __future__ import annotations

import json
import os
from typing import Optional

from .. import ids as _ids
from ..frontends.base import FrontendError
from ..tools import resolve_tool
from .names import fold, path_str
from .oracle import HxDevice, compare, parse_listing, render_closure, run_ngspice

_SUM_KEYS = ("compared", "guarded_hx", "guarded_sim", "unmatched", "name_form", "out_of_scope", "out_of_scope_hx", "mismatches")


def check_ngspice(entry: str, *, root: str, exe: Optional[str] = None, dialect: str = "auto", deck: Optional[str] = None,
                  search_paths=(), timeout: float = 120.0) -> dict:
    """Returns the report dict; `report["status"]` is agree | mismatch | unavailable (the CLI maps it to 0/1/2).

    A whole-deck entry compares every unguarded device; an instance path compares its subtree; a definition-rooted
    entry needs deck context (an explicit --deck, or an entry file that is itself a deck) and is then compared once
    per unguarded instance of the definition in that deck."""
    from ..api import extract, split_entry
    exe = resolve_tool("ngspice", exe)
    file, symbol = split_entry(entry)
    report: dict = {"entry": entry, "oracle": "ngspice", "exe": exe, "status": "unavailable", "summary": None, "mismatches": [], "render": None}
    graph = extract(entry, root=root, depth=None, dialect=dialect, deck=deck, search_paths=list(search_paths), use_cache=True)
    c = graph.circuit
    definition = None
    dgraph = graph
    if c["root"]["kind"] == "definition":
        if c["root"].get("deck_role") != "deck":
            report["reason"] = ("oracle unavailable: no deck context for a definition-rooted entry (name an instance path, '.', "
                                "or pass --deck DECK to compare every instance of the definition in that deck)")
            return report
        definition = graph.nodes[graph.entry]
        dgraph = extract(f"{c['deck']}:.", root=root, depth=None, dialect=dialect, deck=None, search_paths=list(search_paths), use_cache=True)
    fe = _frontend_for(dgraph, root, dialect, search_paths)
    insts: list = []
    unguarded: list = []
    if definition is not None:
        ident = definition.attrs["definition_refs"][0]["key"]
        dfile, dline = definition.loc.file, definition.loc.line
        insts = fe.instances_of(lambda d: d.identity == ident and fe._rel(d.file) == dfile and d.line == dline)
        unguarded = [o for o in insts if not o.gid]
        if not unguarded:                                    # nothing to compare: the simulator is not even started
            report["summary"] = {"instances": 0, "guarded_instances": len(insts)}
            report["reason"] = (f"oracle unavailable: definition '{definition.name}' has no unguarded instance in deck {dgraph.circuit['deck']}"
                                + (f" ({len(insts)} guarded; ngspice lists the active branch only)" if insts else ""))
            return report
    render = render_closure(fe.index)
    report["render"] = render
    proc = run_ngspice(exe, render, os.path.dirname(fe.index.deck), timeout)
    report["ngspice_exit"] = proc.returncode
    report["ngspice_stderr"] = proc.stderr[-4000:]
    listing = parse_listing(proc.stdout)
    if proc.returncode != 0 or not listing.devices and "listing" not in proc.stdout.lower():
        lines = [ln.strip() for ln in (proc.stderr + "\n" + proc.stdout).splitlines() if ln.strip()]
        first = next((ln for ln in lines if any(w in ln.lower() for w in ("error", "undefined", "unknown", "cannot", "not found"))), None)
        last = (proc.stderr.strip().splitlines() or ["(no stderr)"])[-1]
        report["reason"] = f"oracle unavailable: ngspice exit {proc.returncode}: " + (f"{first[:200]} | " if first and first != last else "") + last[:200]
        return report
    devices = _hx_devices(dgraph, fe)
    dc = dgraph.circuit
    hx_models = {k.rsplit("/", 1)[-1] for k in dc["models"]} | {b for rec in dc["models"].values() for b in rec.get("bins", [])}
    report["listing_devices"] = len(listing.devices)
    if definition is not None:
        per = []
        for o in unguarded:
            res = compare(devices, listing, fe.profile, hx_models, list(o.path))
            per.append({"path": path_str(o.path), "summary": res["summary"], "mismatches": res["mismatches"]})
        report["instances"] = per
        report["mismatches"] = [dict(m, instance=p["path"]) for p in per for m in p["mismatches"]]
        summary = {k: sum(p["summary"].get(k, 0) for p in per) for k in _SUM_KEYS}
        summary.update({"instances": len(unguarded), "guarded_instances": len(insts) - len(unguarded), "agree": all(p["summary"]["agree"] for p in per)})
        report["summary"] = summary
        report["status"] = "agree" if summary["agree"] else "mismatch"
        return report
    subtree = None
    if symbol not in (".",):
        entry_node = graph.nodes[graph.entry]
        subtree = entry_node.qualname.split("#")[0].split(".") if entry_node.kind == "instance" else (entry_node.qualname.split("#")[0].split(".")[:-1] if entry_node.kind == "device" else None)
    res = compare(devices, listing, fe.profile, hx_models, subtree)
    report.update(res)
    report["status"] = "agree" if res["summary"]["agree"] else "mismatch"
    return report


def _frontend_for(graph, root, dialect, search_paths):
    """A frontend over the graph's own deck and deck role (a standalone library keeps its line 1), with the same
    traversal re-run so occurrences are registered for every graph node."""
    from ..frontends.spice_fe import SpiceFrontend
    idx = graph.meta.get("index") or {}
    fe = SpiceFrontend(root, deck=idx.get("deck"), dialect=dialect, search_paths=list(search_paths), deck_role=idx.get("deck_role", "deck"))
    fe.build_index()
    from ..traverse import TraverseOptions, extract_graph
    from ..api import split_entry
    file, symbol = split_entry(graph.meta["entry_arg"])
    extract_graph(fe, file, symbol, TraverseOptions(depth=None), root)
    return fe


def _hx_devices(graph, fe) -> list[HxDevice]:
    out: list[HxDevice] = []
    elab = fe._elabs["deck"]
    for nid, n in graph.nodes.items():
        if n.kind != "device":
            continue
        key = fe._by_id.get(nid)
        if key is None:
            continue
        _tag, occ = fe._occ[key]
        rec = elab.device(occ)
        if rec.family is None:
            continue
        chain = elab._ancestors(occ)[1:-1]                     # instance occurrences between the root and the device
        segments = [o.path[-1] for o in chain]
        local_flags = [bool(o.decl is not None and o.decl.scope) for o in chain]
        terminals = [elab.canonical(t["net"], occ) for t in rec.terminals]      # through this device's own ancestors
        model = None
        prefix = None
        if rec.family.model != "none" and rec.parts.master:
            model = fold(rec.parts.master, fe.profile.case_sensitive)
            lk = rec.model_lookup
            if lk is not None and (lk.alternatives or lk.bins):
                d0 = (lk.alternatives or lk.bins)[0]
                if d0.scope:
                    # the instance whose definition declares the model: nearest ancestor with that body scope
                    holder = next((o for o in reversed(chain) if o.decl is not None and o.decl.body_scope == d0.scope), None)
                    prefix = path_str(holder.path) if holder else None
                else:
                    prefix = ""
        refs = []
        for r in rec.refs:
            targets = r["targets"]
            if targets:
                t = targets[0]                                  # alternatives share spelling and scope: one name form
                tchain = elab._ancestors(t)[1:-1]
                refs.append(ngspice_name_for(t.element.letter, [o.path[-1] for o in tchain], [bool(o.decl is not None and o.decl.scope) for o in tchain], t.path[-1]))
            else:
                refs.append(r["as_written"].lower())            # a missing reference has no occurrence; its ghost is a name only
        out.append(HxDevice(node_id=nid, letter=occ.element.letter, name=occ.path[-1], segments=segments, local_flags=local_flags,
                            guarded=bool(occ.gid), terminals=terminals, model=model, model_scope_prefix=prefix, refs=refs, family=rec.family))
    return out


def ngspice_name_for(letter, segments, flags, device):
    from .oracle import ngspice_name
    return ngspice_name(letter, segments, flags, device)


def format_report(report: dict, limit: int = 20) -> str:
    lines = [f"oracle      {report['oracle']} ({report['exe']})", f"entry       {report['entry']}", f"status      {report['status']}"]
    if report.get("reason"):
        lines.append(f"reason      {report['reason']}")
    s = report.get("summary")
    if s and "compared" in s:
        lines.append(f"compared    {s['compared']} devices; guarded hx {s['guarded_hx']}, guarded listing rows {s['guarded_sim']}, "
                     f"out of scope {s.get('out_of_scope', 0)}, unmatched {s['unmatched']}, name-form {s['name_form']}"
                     + (f"; instances {s['instances']} (guarded {s['guarded_instances']})" if "instances" in s else ""))
    for inst in report.get("instances", []):
        si = inst["summary"]
        lines.append(f"instance    {inst['path']}: compared {si['compared']}, mismatches {si['mismatches']}")
    for m in report.get("mismatches", [])[:limit]:
        where = f" @{m['instance']}" if m.get("instance") else ""
        lines.append(f"mismatch    {m['what']:<18} {m['path']}{where}" + (f" [{m['terminal']}]" if m.get("terminal") is not None else "") + f": hx {m['hx']!r} vs {report['oracle']} {m.get('ngspice', m.get('oracle'))!r}")
    if report.get("checked"):
        lines.append("checked     " + ", ".join(report["checked"]))
    if len(report.get("mismatches", [])) > limit:
        lines.append(f"            … {len(report['mismatches']) - limit} more")
    return "\n".join(lines)
