"""Identity helpers: case folding, path segments, net keys and the ONE guard representation.

Guard = frozenset[(chain_id, branch_index)]: one constraint per enclosing `.if/.elseif/.else/.endif` chain, where
chain_id = "<scope path>|<canonical condition tokens of every condition in the chain>" (no ordinal: identical-condition
chains in one scope are one chain). Two guards are compatible when no chain present in both selects different
branches; a child's guard is the union of its parent's and its own; `guard_id` hashes the canonical sorted form.
Lookup, inheritance, hashing, frontend keys and serialisation all use this form."""
from __future__ import annotations

import json
import re
from typing import Iterable, Optional

from .. import ids as _ids

Guard = frozenset  # frozenset[tuple[str, int]]
EMPTY_GUARD: Guard = frozenset()

_ESCAPE = {"\\": "\\\\", ".": "\\.", "#": "\\#", ":": "\\:", "|": "\\|"}
_WS = re.compile(r"\s+")


def fold(name: str, case_sensitive: bool = False) -> str:
    return name if case_sensitive else name.lower()


def escape_segment(seg: str) -> str:
    return "".join(_ESCAPE.get(ch, ch) for ch in seg)


def path_str(segments: Iterable[str], sep: str = ".") -> str:
    return sep.join(escape_segment(s) for s in segments)


def split_path(text: str, sep: str = ".") -> list[str]:
    """Inverse of path_str for user-typed entries: `\\.` keeps a dot inside a segment."""
    out, cur, i = [], [], 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            cur.append(text[i + 1])
            i += 2
            continue
        if ch == sep:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def canonical_condition(text: str, case_sensitive: bool = False) -> str:
    """Condition text reduced to what matters: case-folded outside literals, whitespace removed (`pick>0` ≡ `pick > 0`)."""
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch in "\"'":
            j = text.find(ch, i + 1)
            j = len(text) - 1 if j < 0 else j
            out.append(text[i:j + 1])
            i = j + 1
            continue
        if not ch.isspace():
            out.append(fold(ch, case_sensitive))
        i += 1
    return "".join(out)


def canonical_expr(text: str, case_sensitive: bool = False) -> str:
    """An expression token (`{…}` or `'…'`) reduced to what matters: the outer delimiters kept, the interior with
    whitespace removed and case folded per profile, `"…"` string literals inside it verbatim (`{w * 2}` ≡ `{w*2}`,
    `'W * 2'` ≡ `'w*2'`)."""
    if len(text) >= 2 and ((text[0] == "{" and text[-1] == "}") or (text[0] == text[-1] == "'")):
        head, inner, tail = text[0], text[1:-1], text[-1]
    else:
        head, inner, tail = "", text, ""
    out, i = [], 0
    while i < len(inner):
        ch = inner[i]
        if ch == '"':
            j = inner.find('"', i + 1)
            j = len(inner) - 1 if j < 0 else j
            out.append(inner[i:j + 1])
            i = j + 1
            continue
        if not ch.isspace():
            out.append(fold(ch, case_sensitive))
        i += 1
    return head + "".join(out) + tail


def chain_id(scope: tuple[str, ...], conditions: Iterable[str], case_sensitive: bool = False) -> str:
    return path_str(scope, "/") + "|" + " ; ".join(canonical_condition(c, case_sensitive) for c in conditions)


def guard_compatible(a: Guard, b: Guard) -> bool:
    da = dict(a)
    return all(da.get(c, i) == i for c, i in b)


def guard_union(a: Guard, b: Guard) -> Guard:
    return frozenset(a | b)


def guard_exclusive(a: Guard, b: Guard) -> bool:
    return not guard_compatible(a, b)


def guard_sorted(g: Guard) -> list[tuple[str, int]]:
    return sorted(g)


def guard_id(g: Guard) -> str:
    if not g:
        return ""
    return _ids.short_hash(json.dumps(guard_sorted(g)), 8)


def guard_json(g: Guard) -> list[dict]:
    return [{"chain": c, "branch": i} for c, i in guard_sorted(g)]


def guard_from_json(items: Optional[list[dict]]) -> Guard:
    return frozenset((d["chain"], int(d["branch"])) for d in (items or []))


def guard_text(g: Guard) -> str:
    """Human form for notes and the viewer: `scope|cond#branch` entries joined by ` & `."""
    return " & ".join(f"{c.split('|', 1)[1] or '?'}#{i}" for c, i in guard_sorted(g))


def decl_identity(scope: tuple[str, ...], name: str, gid: str = "") -> str:
    """`scope/name#<guard_id>`: the identity of one declaration (an alternative under a guard); `#` omitted when unconditional."""
    base = path_str(scope, "/") + "/" + name if scope else "/" + name
    return base + (f"#{gid}" if gid else "")
