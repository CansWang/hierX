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
from typing import Any, Optional

SCHEMA = "hx/1"

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
    value: int


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
        import os
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())
            fh.write("\n")

    @classmethod
    def from_dict(cls, d: dict) -> "Graph":
        return _de(cls, d)

    @classmethod
    def load(cls, path: str) -> "Graph":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


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
