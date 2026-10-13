"""Language-neutral intermediate representation (IR) for hx graphs.

Plain dataclasses only, so a graph round-trips through JSON without any
language frontend being importable. JSON keys "from"/"to" map to the Python
attributes `src`/`dst` (reserved words).
"""
from __future__ import annotations

import datetime as _dt
import json
import typing
from dataclasses import dataclass, field, fields as _dc_fields, is_dataclass
from typing import Any, Optional, Union

SCHEMA = "hx/3"          # "<name>/<major>": a different major is incompatible; fields may be ADDED within a major
# hx/3 (2026-10, 0.4.0): ids changed for nested LSP functions (enclosing functions are part of the qualified name),
# Python module callers (`module` nodes), C/C++ non-external symbols and all C/C++ types (keyed by defining file,
# `@<8hex>` fingerprint when translation units disagree) and symlinked paths (resolved); Python stub overload
# families collapse to one target with `family` metadata on the unresolved record.
# hx/2 (2026-10): ids changed for module-scoped SV types (layout fingerprint), anonymous SV types (declaring
# context) and Verilator generate-array spelling; values >= 2**53 are strings (see hx/values.py). hx/1 and hx/2
# files are upgraded in memory by hx/graphio.py (relabel + report; `hx migrate` re-extracts).


class SchemaError(ValueError):
    """The document's `schema` is missing or belongs to another major version."""


def check_schema(d: Any) -> None:
    if not isinstance(d, dict):
        raise SchemaError("graph document is not a JSON object")
    s = d.get("schema")
    if s is None:
        raise SchemaError(f"graph has no 'schema' field (expected {SCHEMA!r})")
    name, _, major = str(s).partition("/")
    want_name, _, want_major = SCHEMA.partition("/")
    if name != want_name or major.split(".")[0] != want_major:
        raise SchemaError(f"unsupported graph schema {s!r}: this hx reads {SCHEMA!r}")

_RENAME = {"src": "from", "dst": "to"}
_UNRENAME = {v: k for k, v in _RENAME.items()}


@dataclass
class Loc:
    file: str
    line: int
    end_line: Optional[int] = None
    col: Optional[int] = None


@dataclass
class TypeUse:
    type: str
    type_ref: Optional[str] = None


@dataclass
class Param:
    name: str
    type: str
    type_ref: Optional[str] = None
    dir: str = "in"                 # in | out | inout
    dir_source: str = "heuristic"   # explicit | heuristic | user


@dataclass
class Field:
    name: str
    type: str
    type_ref: Optional[str] = None
    offset: Optional[int] = None      # byte offset within the parent
    size: Optional[int] = None        # bytes; None for bitfields / incomplete
    bit_offset: Optional[int] = None  # bitfields: bit offset within the byte at `offset`
    bit_width: Optional[int] = None   # bitfields only


@dataclass
class Enumerator:
    name: str
    value: Union[int, str, None]   # JSON number when |v| < 2**53, else canonical string (hx/values.py); x/z keep their pattern


@dataclass
class TypeDef:
    id: str
    kind: str            # struct | union | class | enum | typedef | ...
    name: str
    lang: str
    loc: Optional[Loc] = None
    size: Optional[int] = None
    align: Optional[int] = None
    fields: list[Field] = field(default_factory=list)
    enumerators: list[Enumerator] = field(default_factory=list)
    underlying: Optional[str] = None       # typedef/enum: spelled underlying type
    underlying_ref: Optional[str] = None   # typedef: id of the aliased type, if any
    anonymous: bool = False
    system: bool = False                   # declared in a system header (fields omitted unless --include-system)
    used_by: list[str] = field(default_factory=list)


@dataclass
class GlobalRefs:
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)


@dataclass
class Node:
    id: str
    kind: str            # function | method | module | instance | task ...
    name: str
    qualname: str
    lang: str
    loc: Loc
    signature: str
    storage: Optional[str] = None      # extern | static
    depth: int = 0                     # min BFS depth from entry; negative = caller side
    body_hash: Optional[str] = None
    precision: str = "exact"           # exact | lsp | syntax
    returns: Optional[TypeUse] = None
    params: list[Param] = field(default_factory=list)
    globals: GlobalRefs = field(default_factory=GlobalRefs)
    calls: list[str] = field(default_factory=list)   # ids of expanded targets (see edges for kind)
    attrs: dict[str, Any] = field(default_factory=dict)  # frontend extras (e.g. SV: module, parameters, signals)
    runtime: Any = None                # reserved (Phase 5)


@dataclass
class GlobalVar:
    id: str
    name: str
    type: str
    lang: str
    type_ref: Optional[str] = None
    loc: Optional[Loc] = None
    storage: Optional[str] = None
    scope: str = "file"                # file | function-static | member


@dataclass
class Edge:
    src: str
    dst: Optional[str]
    kind: str                          # call | ref | fnptr | macro | instance
    loc: Optional[Loc] = None
    args: list[str] = field(default_factory=list)
    name: Optional[str] = None         # callee as written at the call site
    macro: Optional[str] = None        # macro the call was expanded from
    ptr_type: Optional[str] = None     # fnptr: type of the pointer


@dataclass
class Unresolved:
    name: str
    src: str
    reason: str
    loc: Optional[Loc] = None
    id: Optional[str] = None           # declared-but-not-expanded id, if known
    family: Optional[dict] = None      # hx/3: {size, evidence, scope} when the target is a collapsed stub overload family


@dataclass
class Graph:
    root: str
    lang: str
    entry: str
    schema: str = SCHEMA
    generated: str = field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"))
    nodes: dict[str, Node] = field(default_factory=dict)
    types: dict[str, TypeDef] = field(default_factory=dict)
    globals: dict[str, GlobalVar] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    _ORDER = ("schema", "generated", "root", "lang", "entry", "meta",
              "nodes", "types", "globals", "edges", "unresolved")

    def to_dict(self) -> dict:
        d = _ser(self)
        return {k: d[k] for k in self._ORDER if k in d}

    def to_json(self, indent: Optional[int] = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save(self, path: str) -> None:
        from .fsutil import atomic_write
        atomic_write(path, self.to_json() + "\n")

    @classmethod
    def from_dict(cls, d: dict) -> "Graph":
        check_schema(d)
        return _de(cls, d)

    @classmethod
    def load(cls, path: str) -> "Graph":
        from .graphio import load_graph_dict   # the shared reader: wide values, hx/1 upgrade in memory
        return cls.from_dict(load_graph_dict(path))


# ---------------------------------------------------------------- (de)serialization

def _ser(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        out = {}
        for f in _dc_fields(obj):
            if f.name.startswith("_"):
                continue
            out[_RENAME.get(f.name, f.name)] = _ser(getattr(obj, f.name))
        return out
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_ser(v) for v in obj]
    return obj


def _de(cls: type, d: Any) -> Any:
    """Rebuild dataclass `cls` from a JSON dict, recursing by type hints."""
    if d is None:
        return None
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in _dc_fields(cls):
        if f.name.startswith("_"):
            continue
        key = _RENAME.get(f.name, f.name)
        if key not in d:
            continue
        kwargs[f.name] = _de_value(hints[f.name], d[key])
    return cls(**kwargs)


def _de_value(hint: Any, v: Any) -> Any:
    if v is None:
        return None
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin is typing.Union:
        inner = [a for a in args if a is not type(None)]
        return _de_value(inner[0], v) if len(inner) == 1 else v
    if origin in (list, tuple):
        return [_de_value(args[0], x) for x in v] if args else list(v)
    if origin is dict:
        return {k: _de_value(args[1], x) for k, x in v.items()} if args else dict(v)
    if isinstance(hint, type) and is_dataclass(hint):
        return _de(hint, v)
    return v
