"""Compose upstream parsing, Hx interpretation and optional navigation bindings."""
from __future__ import annotations

from .bindings import resolve_navigation
from .bridge import compile_d2
from .interpret import interpret
from .model import ArchitectureDocument


def load_architecture(design: str, *, root: str | None = None, graph: str | None = None,
                      bridge: str | None = None, timeout: float = 30) -> ArchitectureDocument:
    """Read a D2 design and optionally resolve navigation against one saved graph.

    Inputs are read-only. No extraction, ownership projection, type compatibility,
    required-connection check, or conformance verdict is performed.
    """
    doc = interpret(compile_d2(design, root, bridge, timeout))
    resolve_navigation(doc, graph)
    return doc
