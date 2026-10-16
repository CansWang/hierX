"""Netlist token hashes (`sha1:` like every other hx body hash): case folded per profile outside literals, comments,
continuation layout and whitespace removed; string tokens verbatim; expression tokens (`{…}`, `'…'`) with their
interior whitespace removed and case folded (`names.canonical_expr`), inner string literals verbatim. The C-oriented
`ids.lex` is never used for netlists (`*` would be an operator there)."""
from __future__ import annotations

import hashlib
from typing import Iterable, Union

from .lexer import tokenize
from .names import canonical_expr
from .profiles import Profile


def canonical_tokens(text: str, profile: Profile) -> list[str]:
    out = []
    for t in tokenize(text, profile):
        if t.kind == "string":
            out.append(t.text)
        elif t.kind == "expr":
            out.append(canonical_expr(t.text, profile.case_sensitive))
        else:
            out.append(t.text if profile.case_sensitive else t.text.lower())
    return out


def statement_hash(text: str, profile: Profile) -> str:
    return "sha1:" + hashlib.sha1(" ".join(canonical_tokens(text, profile)).encode("utf-8", "replace")).hexdigest()


def scope_hash(items: Iterable[Union[str, tuple[str, str]]], profile: Profile) -> str:
    """Hash of a scope's statements IN ORDER (reordering inside a scope changes it; nothing outside does). An item is
    a statement text or a `(prefix, text)` pair; the prefix carries the statement's guard (its `.if` chain and
    branch), so a condition-only edit moves the hash of the scope that holds the conditional."""
    h = hashlib.sha1()
    for it in items:
        prefix, text = it if isinstance(it, tuple) else ("", it)
        if prefix:
            h.update(prefix.encode("utf-8", "replace"))
            h.update(b"\0")
        h.update(" ".join(canonical_tokens(text, profile)).encode("utf-8", "replace"))
        h.update(b"\n")
    return "sha1:" + h.hexdigest()
