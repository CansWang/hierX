"""Stable identifiers and hashing.

IDs must survive regeneration so annotations can be keyed by them:
    <lang>:<relpath>::<qualname>[#<8-hex>]        functions
    <lang>:<relpath>::struct <name>               records/enums ("struct", "union", "class", "enum")
    <lang>:<relpath>::<name>                      typedefs / aliases
    <lang>:<relpath>::anon@L<line>                anonymous records
    <lang>:<relpath>::<name> | <func>.<name>      globals / function-local statics
The 8-hex suffix is added only when two symbols would otherwise collide
(C++ overloads), so most IDs stay human-readable.
"""
from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from typing import Iterable

_WS = re.compile(rb"\s+")
RECORD_KINDS = ("struct", "union", "class", "enum")


def short_hash(s: str, n: int = 8) -> str:
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:n]


def body_hash(text: bytes | str) -> str:
    """Whitespace-insensitive content hash, so reformatting does not read as a change."""
    if isinstance(text, str):
        text = text.encode("utf-8", "replace")
    norm = _WS.sub(b" ", text).strip()
    return "sha1:" + hashlib.sha1(norm).hexdigest()


def rel(path: str, root: str) -> str:
    """Path relative to root when inside it, else the absolute path (external/system files)."""
    path = os.path.abspath(path)
    root = os.path.abspath(root)
    try:
        r = os.path.relpath(path, root)
    except ValueError:  # different drive (Windows)
        return path
    if r.startswith(".."):
        return path
    return r.replace(os.sep, "/")


def node_id(lang: str, relpath: str, qualname: str, disambiguator: str | None = None) -> str:
    base = f"{lang}:{relpath}::{qualname}"
    return f"{base}#{disambiguator}" if disambiguator else base


def type_id(lang: str, relpath: str, kind: str, name: str, *, anonymous: bool = False, line: int | None = None) -> str:
    if anonymous or not name:
        return f"{lang}:{relpath}::anon@L{line if line is not None else 0}"
    if kind in RECORD_KINDS:
        return f"{lang}:{relpath}::{kind} {name}"
    return f"{lang}:{relpath}::{name}"


def var_id(lang: str, relpath: str, qualname: str) -> str:
    return f"{lang}:{relpath}::{qualname}"


def disambiguate(keyed_ids: dict[str, str]) -> dict[str, str]:
    """Given key -> candidate id, append '#<hash(key)>' to every id that is shared by >1 key."""
    groups: dict[str, list[str]] = defaultdict(list)
    for key, cid in keyed_ids.items():
        groups[cid].append(key)
    out = {}
    for cid, keys in groups.items():
        if len(keys) == 1:
            out[keys[0]] = cid
        else:
            for k in keys:
                out[k] = f"{cid}#{short_hash(k)}"
    return out
