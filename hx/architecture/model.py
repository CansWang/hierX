"""Authored architecture model. Geometry and observed code remain separate."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


class ArchitectureError(ValueError):
    """A tool, input, or protocol prevents architecture compilation."""


@dataclass
class ArchitectureDocument:
    """Versioned derived intent; links are navigation, never conformance evidence.

    Interpretation produces this document before any layout takes place. Future
    bundle normalization can produce ordinary endpoint records here; layout and
    presentation need not learn a second authoring grammar. No bus syntax is
    accepted by this version.
    """

    schema: str = "hx-arch/1"
    blocks: list[dict] = field(default_factory=list)
    ports: list[dict] = field(default_factory=list)
    connections: list[dict] = field(default_factory=list)
    bindings: dict[str, dict] = field(default_factory=dict)
    inputs: list[dict] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    tools: dict = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not any(d["severity"] == "error" for d in self.diagnostics)

    def to_dict(self) -> dict:
        """Return JSON-compatible authored structure and diagnostics."""
        return {**asdict(self), "valid": self.valid}
