"""Hx interpretation of compiled D2; independent of upstream parsing and layout."""
from __future__ import annotations

from .model import ArchitectureDocument

ROLES = {"hx-input", "hx-output", "hx-block", "hx-exposure", "hx-wire"}


def interpret(compiled: dict) -> ArchitectureDocument:
    """Interpret the ordinary-port profile without contractual validation."""
    doc = ArchitectureDocument(inputs=compiled["inputs"], tools={
        "d2_version": compiled["d2_version"], "d2_commit": compiled["d2_commit"],
        "bridge_protocol": compiled["protocol"],
    })

    def diagnostic(code, subject, message, severity="error", sources=None):
        doc.diagnostics.append({"code": code, "subject": subject, "message": message,
                                "severity": severity, "sources": sources or []})

    for d in compiled["diagnostics"]:
        diagnostic(d["code"], d.get("file", ""), d["message"], sources=[
            {k: d[k] for k in ("file", "line", "column") if k in d}])
    if not compiled["ok"]:
        return doc
    if not compiled["objects"]:
        diagnostic("empty-architecture", "", "Declare at least one architecture block")
    if compiled["boards"]:
        diagnostic("unsupported-d2-boards", "", "D2 layers, steps and scenarios are outside the Hx architecture profile")
    if compiled["presentation"]:
        diagnostic("d2-presentation-ignored", "", "Hx controls layout and theme; D2 layout configuration is ignored", "warning")
    objects = {}
    for o in compiled["objects"]:
        if o["id"] in objects:
            diagnostic("duplicate-identity", o["id"], "Duplicate compiled object identity")
        objects[o["id"]] = o
        classes = set(o["classes"] or [])
        unknown = {c for c in classes if c.startswith("hx-")} - ROLES
        roles = classes & {"hx-input", "hx-output", "hx-block"}
        if unknown or len(roles) > 1 or classes & {"hx-wire", "hx-exposure"}:
            diagnostic("unsupported-hx-role", o["id"], "Unknown, conflicting, or misplaced Hx role", sources=o["sources"])
        record = {k: o[k] for k in ("id", "path", "label", "sources")}
        if roles & {"hx-input", "hx-output"}:
            record.update(block=o["parent"], direction="in" if "hx-input" in roles else "out")
            doc.ports.append(record)
        else:
            record["parent"] = o["parent"] or None
            doc.blocks.append(record)
        if o.get("presentation"):
            diagnostic("d2-presentation-ignored", o["id"], "Hx controls shapes, dimensions and styling in this profile", "warning", o["sources"])
        if o["link"]:
            if o["link"].startswith("hx:") and o["link"][3:]:
                doc.bindings[o["id"]] = {"symbol": o["link"][3:], "status": "unresolved"}
            else:
                diagnostic("unsupported-code-link", o["id"], "Code links use hx:<exact-saved-node-id>", sources=o["sources"])
    blocks = {b["id"]: b for b in doc.blocks}
    ports = {p["id"]: p for p in doc.ports}
    for block in doc.blocks:
        if block["parent"] and block["parent"] not in blocks:
            diagnostic("invalid-block-owner", block["id"], "A block must be nested in another block")
    for port in doc.ports:
        if port["block"] not in blocks:
            diagnostic("invalid-port-owner", port["id"], "A port must be an immediate child of a block")
    seen = set()
    for e in compiled["edges"]:
        classes = set(e["classes"] or [])
        if {c for c in classes if c.startswith("hx-")} - {"hx-exposure", "hx-wire"} or {"hx-exposure", "hx-wire"} <= classes:
            diagnostic("unsupported-hx-role", e["id"], "Unknown, conflicting, or misplaced connection role")
        kind = "exposure" if "hx-exposure" in classes else "wire"
        if not e["forward"]:
            diagnostic("unsupported-arrow", e["id"], "Use directed -> connections between explicit ports")
        a, b = ports.get(e["source"]), ports.get(e["target"])
        valid = False
        if a and b and a["block"] in blocks and b["block"] in blocks:
            if kind == "wire":
                valid = (a["direction"], b["direction"]) == ("out", "in") and a["block"] != b["block"] and blocks[a["block"]]["parent"] == blocks[b["block"]]["parent"]
            else:
                valid = ((a["direction"], b["direction"]) == ("in", "in") and blocks[b["block"]]["parent"] == a["block"]) or ((a["direction"], b["direction"]) == ("out", "out") and blocks[a["block"]]["parent"] == b["block"])
        if not valid:
            diagnostic("invalid-endpoints", e["id"], "Wires join sibling output/input ports; explicit exposures join matching parent/child port directions", sources=e["sources"])
        if e["id"] in seen:
            diagnostic("duplicate-identity", e["id"], "Duplicate compiled edge identity")
        seen.add(e["id"])
        doc.connections.append({**{k: e[k] for k in ("id", "source", "target", "label", "sources")}, "kind": kind})
        if e.get("presentation"):
            diagnostic("d2-presentation-ignored", e["id"], "Hx controls connection styling and arrowheads", "warning", e["sources"])
    return doc
