"""Navigation resolution only; no ownership projection or evidence verdicts."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..graphio import load_graph_text, upgrade
from .model import ArchitectureDocument, ArchitectureError


def resolve_navigation(doc: ArchitectureDocument, graph: str | None) -> None:
    """Attach exact code lookup results and the hash of the graph bytes read."""
    nodes = {}
    if graph:
        raw = Path(graph).read_bytes()
        saved, _ = upgrade(load_graph_text(raw.decode("utf-8")))
        nodes = saved.get("nodes", {})
        if not isinstance(nodes, dict) or not all(isinstance(n, dict) for n in nodes.values()):
            raise ArchitectureError("Saved graph nodes must be an object of node records")
        doc.inputs.append({"file": str(Path(graph).resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "kind": "code-graph"})
    for identity, binding in doc.bindings.items():
        node = nodes.get(binding["symbol"])
        if node:
            binding.update(status="resolved", signature=node.get("signature", ""), loc=node.get("loc"))
        else:
            doc.diagnostics.append({"code": "unresolved-code-link", "subject": identity,
                                    "message": "Code target is absent from the explicitly supplied graph" if graph else "Supply --graph to resolve this code link",
                                    "severity": "warning", "sources": []})
