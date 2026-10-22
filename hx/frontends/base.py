"""Frontend protocol: what a language plugin must provide to the traversal.

Keys are frontend-internal (libclang USRs, LSP item handles, SV instance
paths); the frontend maps them to stable IDs. The traversal never looks inside
a key.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from ..model import Loc, Node, TypeDef, GlobalVar


class FrontendError(Exception):
    """A frontend could not initialize, index, or extract the requested entry."""
    pass


class EntryNotFound(FrontendError):
    """Entry lookup failed; suggestions contains possible symbol alternatives."""
    def __init__(self, message: str, suggestions: list[str] | None = None):
        super().__init__(message)
        self.suggestions = suggestions or []


@dataclass
class CallSite:
    callee_key: Optional[str]      # None for calls that cannot be resolved (function pointers)
    name: str                      # callee as written / resolved name
    loc: Optional[Loc]
    kind: str = "call"             # call | ref | fnptr | macro
    args: list[str] = field(default_factory=list)
    macro: Optional[str] = None
    ptr_type: Optional[str] = None


@dataclass
class FunctionRecord:
    node: Node
    callsites: list[CallSite]
    type_keys: list[str]           # types referenced by signature (and globals)
    global_keys: list[str]


@dataclass
class DeclRecord:
    id: str
    name: str
    loc: Optional[Loc]
    has_definition: bool
    system: bool
    relpath: Optional[str]         # for --exclude matching
    reason: Optional[str] = None   # frontend-specific wording for why it cannot be expanded
    family: Optional[dict] = None  # verified stub overload family this target stands for: {size, evidence, scope}


@dataclass
class TypeRecord:
    typedef: TypeDef
    nested_keys: list[str]         # field types (consume a level of --type-depth)
    alias_keys: list[str]          # typedef underlying (free: same level)


class Frontend(ABC):
    lang: str = "?"

    def evidence_limits(self) -> list[str]:
        """Known omission codes; an empty list is not proof of completeness."""
        return []

    def provenance_inputs(self) -> dict[str, Optional[int]]:
        """Observed absolute input paths and mtimes; None represents a missing input.

        This is an observed subset, including on cache hits, not a complete
        account of inputs consumed internally by compilers or language servers.
        """
        return {}

    @abstractmethod
    def locate_entry(self, file: str, symbol: str) -> str: ...

    @abstractmethod
    def function(self, key: str) -> Optional[FunctionRecord]:
        """Full record for a function *definition*, or None if only declared."""

    @abstractmethod
    def declaration(self, key: str) -> Optional[DeclRecord]: ...

    @abstractmethod
    def type(self, key: str) -> Optional[TypeRecord]: ...

    @abstractmethod
    def global_var(self, key: str) -> Optional[GlobalVar]: ...

    @abstractmethod
    def callers(self, key: str) -> list[tuple[str, CallSite]]:
        """(caller_key, callsite) pairs for every known call into `key`."""

    @abstractmethod
    def stable_id(self, key: str) -> Optional[str]: ...
