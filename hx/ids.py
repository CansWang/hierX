"""Stable identifiers and hashing.

IDs must survive regeneration so annotations can be keyed by them:
    <lang>:<relpath>::<qualname>[#<8-hex>]        functions
    <lang>:<relpath>::struct <name>               records/enums ("struct", "union", "class", "enum")
    <lang>:<relpath>::<name>                      typedefs / aliases
    <lang>:<relpath>::<kind> <parent>.<member>    anonymous records (named after the member that holds them)
    <lang>:<relpath>::<name> | <func>.<name>      globals / function-local statics
The 8-hex suffix is added only when two symbols would otherwise collide
(C++ overloads), so most IDs stay human-readable.
"""
from __future__ import annotations

import functools
import hashlib
import os
import re
from collections import defaultdict
from typing import NamedTuple

RECORD_KINDS = ("struct", "union", "class", "enum")

# Operators lexed by maximal munch, so `a--b` (tokens a, --, b) differs from `a - -b` (a, -, -, b) while
# `x+1` and `x + 1` tokenize identically. Covers C/C++, Rust, SystemVerilog and Python.
_MULTI_OPS = sorted({
    "<<<=", ">>>=", "<<=", ">>=", "...", "->*", "<=>", "**=", "//=", "..=", "===", "!==", "==?", "!=?", "<<<", ">>>", "->>",
    "::", "->", "++", "--", "<<", ">>", "<=", ">=", "==", "!=", "&&", "||", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
    "##", "**", "//", "=>", "<-", "..", "+:", "-:", ":=", "@=", "~&", "~|", "~^", "^~", "<->", "@@",
}, key=len, reverse=True)
_PY_STR_PREFIX = re.compile(r"^(?:[rR][bB]?|[bB][rR]?|[uU]|[fF][rR]?|[rR][fF])$")
_C_RAW_PREFIX = {"R", "LR", "uR", "UR", "u8R"}


def short_hash(s: str, n: int = 8) -> str:
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:n]


def _lang_mode(lang: str | None) -> str:
    lang = (lang or "c").lower()
    if lang in ("py", "python"):
        return "py"
    if lang in ("rs", "rust"):
        return "rs"
    if lang in ("sv", "v", "verilog", "systemverilog"):
        return "sv"
    return "c"


class Tok(NamedTuple):
    """One lexed token with its source span: `text == source[start:end]` for every kind except `indent`.
    Python `indent` tokens (`\\n<n>`) are synthetic: `start == end`, at the first character of the logical line."""
    kind: str      # ident | number | string | char | op | indent
    text: str
    start: int
    end: int


def lex(text: str, lang: str | None = "c") -> list[Tok]:
    """Split source text into tokens, keeping spans. What is kept and what is dropped:
    kept   identifiers, numbers, operators (maximal munch), string/char literals VERBATIM (their inner whitespace counts),
           and for Python the indentation of every logical line (relative to the first line; tabs count as 8)
    dropped comments (//, /* */, Python #), all other whitespace, blank lines, Python line continuations.
    Language rules: Python strings take '/\"/triple quotes and r/b/u/f prefixes, `#` comments; C takes string/char
    literals, `R\"d(...)d\"` raw strings and both comment forms; Rust distinguishes lifetimes (`'a`) from chars and lexes
    `r#\"...\"#`; SystemVerilog lexes based numbers (`8'hFF`). `<` and `>` are plain operators in every language."""
    mode = _lang_mode(lang)
    py, rs, sv = mode == "py", mode == "rs", mode == "sv"
    out: list[Tok] = []
    i, n = 0, len(text)
    depth = 0                # bracket depth: Python suppresses indentation tokens inside brackets
    last_end = -1            # end offset of the previous token (adjacency test for prefixed literals)
    base_indent: int | None = None

    def indent_of(j: int) -> tuple[int, int]:
        k, ind = j, 0
        while k < n and text[k] in " \t":
            ind += 8 if text[k] == "\t" else 1
            k += 1
        return k, ind

    def scan_quoted(j: int, quote: str, multiline: bool) -> int:
        """j is just past the opening quote; returns the offset just past the closing quote."""
        while j < n:
            c = text[j]
            if c == "\\":
                j += 2
                continue
            if c == quote:
                return j + 1
            if c == "\n" and not multiline:
                return j
            j += 1
        return n

    def scan_triple(j: int, quote: str) -> int:
        q3 = quote * 3
        while j < n:
            if text[j] == "\\":
                j += 2
                continue
            if text.startswith(q3, j):
                return j + 3
            j += 1
        return n

    if py:
        k, ind = indent_of(0)
        base_indent = ind
        i = k

    while i < n:
        ch = text[i]
        if ch == "\n":
            i += 1
            if not py or depth:
                continue
            # python: emit the indentation of the next logical line (skipping blank and comment-only lines)
            while True:
                k, ind = indent_of(i)
                if k < n and text[k] == "\n":
                    i = k + 1
                    continue
                if k < n and text[k] == "#":
                    while k < n and text[k] != "\n":
                        k += 1
                    i = k + 1 if k < n else k
                    continue
                break
            if k < n and out:                      # no indentation token before the first real token
                out.append(Tok("indent", f"\\n{max(0, ind - (base_indent or 0))}", k, k))
            i = k
            continue
        if ch in " \t\r\f\v":
            i += 1
            continue
        if py and ch == "\\" and i + 1 < n and text[i + 1] == "\n":
            i += 2
            continue
        # ---- comments
        if py and ch == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if not py and ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if not py and ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        start = i
        # ---- string literals
        if ch == '"' or (py and ch == "'"):
            if py and text.startswith(ch * 3, i):
                i = scan_triple(i + 3, ch)
            else:
                i = scan_quoted(i + 1, ch, multiline=rs)
            tok = Tok("string", text[start:i], start, i)
            if out and last_end == start and (py and _PY_STR_PREFIX.match(out[-1].text)):
                prev = out.pop()
                tok = Tok("string", prev.text + tok.text, prev.start, i)
            out.append(tok)
            last_end = i
            continue
        if ch == "'":
            if sv:   # 8'hFF, 'h10, '0, '1, 'x : part of a number
                j = i + 1
                if j < n and text[j] in "sS":
                    j += 1
                if j < n and text[j] in "bBoOdDhH":
                    j += 1
                while j < n and (text[j].isalnum() or text[j] in "_?"):
                    j += 1
                tok = Tok("number", text[i:j], i, j)
                if out and last_end == start and out[-1].text[0].isdigit():
                    prev = out.pop()
                    tok = Tok("number", prev.text + tok.text, prev.start, j)
                out.append(tok)
                i = last_end = j
                continue
            if rs and not (i + 1 < n and text[i + 1] == "\\") and not (i + 2 < n and text[i + 2] == "'"):
                j = i + 1   # lifetime 'a
                while j < n and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                out.append(Tok("ident", text[i:j], i, j))
                i = last_end = j
                continue
            i = scan_quoted(i + 1, "'", multiline=False)
            if i - start > 24:        # not a char literal after all (e.g. an unbalanced quote in a macro): plain operator
                i = start + 1
                out.append(Tok("op", text[start:i], start, i))
            else:
                out.append(Tok("char", text[start:i], start, i))
            last_end = i
            continue
        # ---- words (identifiers, keywords) incl. prefixed/raw string literals
        if ch.isalpha() or ch in "_$":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            word = text[i:j]
            kind = "ident"
            if j < n and text[j] == '"' and mode == "c" and word in _C_RAW_PREFIX:          # R"delim( ... )delim"
                lp = text.find("(", j)
                delim = text[j + 1:lp] if lp > 0 else ""
                close = text.find(")" + delim + '"', lp if lp > 0 else j)
                j = n if close < 0 else close + len(delim) + 2
                word, kind = text[i:j], "string"
            elif rs and word in ("r", "br") and j < n and text[j] in '#"':                 # r#"..."#
                k = j
                while k < n and text[k] == "#":
                    k += 1
                hashes = k - j
                if k < n and text[k] == '"':
                    close = text.find('"' + "#" * hashes, k + 1)
                    j = n if close < 0 else close + 1 + hashes
                    word, kind = text[i:j], "string"
            out.append(Tok(kind, word, i, j))
            i = last_end = j
            continue
        # ---- numbers (pp-number style: digits, letters, '.', exponent signs)
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i + 1
            while j < n:
                c = text[j]
                if c.isalnum() or c in "_.":
                    j += 1
                elif c in "+-" and text[j - 1] in "eEpP" and "x" not in text[i:j].lower():
                    j += 1
                else:
                    break
            out.append(Tok("number", text[i:j], i, j))
            i = last_end = j
            continue
        # ---- operators / punctuation
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        for op in _MULTI_OPS:
            if text.startswith(op, i):
                out.append(Tok("op", op, i, i + len(op)))
                i += len(op)
                break
        else:
            out.append(Tok("op", ch, i, i + 1))
            i += 1
        last_end = i
    return out


def tokenize(text: str, lang: str | None = "c") -> list[str]:
    """Token texts of `lex(text, lang)` (what `body_hash` hashes)."""
    return [t.text for t in lex(text, lang)]


# ---------------------------------------------------------------- expression text helpers built on `lex`

_NO_SPACE_AFTER = {"(", "[", "{"}
_NO_SPACE_BEFORE = {")", "]", "}", ",", ";"}


def _join(toks: list[Tok]) -> str:
    """Tokens back to text: tokens adjacent in the source stay glued; any gap (whitespace, a removed comment, a
    line break) becomes exactly one space, except that no space is written after an opening bracket or before a
    closing bracket, comma or semicolon (`f( a , b )` -> `f(a, b)`). Literal interiors are untouched because a
    literal is one token, and operator adjacency is preserved (`a - -b` never becomes `a--b`)."""
    if not toks:
        return ""
    parts = [toks[0].text]
    for a, b in zip(toks, toks[1:]):
        glue = a.end == b.start or (a.kind == "op" and a.text in _NO_SPACE_AFTER) or (b.kind == "op" and b.text in _NO_SPACE_BEFORE)
        parts.append(("" if glue else " ") + b.text)
    return "".join(parts)


def _code_tokens(text: str, lang: str | None) -> list[Tok]:
    return [t for t in lex(text, lang) if t.kind != "indent"]


_ANGLE_STEP = {"<": 1, "<<": 2, ">": -1, ">>": -2}


def _depth_step(t: Tok, angle: bool) -> int:
    """Bracket depth change of one token: `([{` / `)]}` always; `<`/`>` (and `<<`/`>>`) only when `angle`,
    which is meant for Rust generics in signatures — never `->`, `<=`, `>=`, `=>`, `<-`, which are their own tokens."""
    if t.kind != "op":
        return 0
    if t.text in ("(", "[", "{"):
        return 1
    if t.text in (")", "]", "}"):
        return -1
    return _ANGLE_STEP.get(t.text, 0) if angle else 0


def _split_tokens(toks: list[Tok], sep: str, angle: bool) -> list[list[Tok]]:
    out: list[list[Tok]] = []
    cur: list[Tok] = []
    depth = 0
    for t in toks:
        if t.kind == "op" and t.text == sep and depth == 0:
            out.append(cur)
            cur = []
            continue
        depth = max(0, depth + _depth_step(t, angle))
        cur.append(t)
    out.append(cur)
    return out


def squash_ws(text: str, lang: str | None = "c") -> str:
    """Expression/signature text with formatting removed but meaning kept: comments dropped, every run of
    whitespace (or a removed comment, or a line break) between tokens becomes one space, adjacent tokens stay
    glued (`pc->x`), string/char literals are preserved byte for byte (`"   "` stays three spaces)."""
    return _join(_code_tokens(text, lang))


def split_top(text: str, lang: str | None = "c", *, sep: str = ",", angle: bool = False) -> list[str]:
    """Split `text` at top-level `sep` tokens, honouring brackets and never splitting inside a literal or a
    comment. `angle=True` (Rust signatures) also treats `<`/`>` as brackets so `d<x, y>` stays whole.
    Parts are squashed like `squash_ws`; empty parts are dropped."""
    parts = (_join(p) for p in _split_tokens(_code_tokens(text, lang), sep, angle))
    return [p for p in parts if p]


def paren_span(text: str, lang: str | None = "c") -> tuple[int, int] | None:
    """Character offsets `(open, close)` of the first `(` token in `text` and its matching `)`, matched over
    `([{` / `)]}` tokens only (never inside a literal or comment); None when the list is not complete."""
    toks = _code_tokens(text, lang)
    o = next((i for i, t in enumerate(toks) if t.kind == "op" and t.text == "("), None)
    if o is None:
        return None
    depth = 0
    for j in range(o, len(toks)):
        depth += _depth_step(toks[j], False)
        if depth == 0:
            return toks[o].start, toks[j].start
    return None


def paren_args(text: str, lang: str | None = "c", *, angle: bool = False, keep_empty: bool = False) -> list[str]:
    """Arguments of the first parenthesised list in `text`: `'MAC(a, f(b, c), "x, y")'` -> `['a', 'f(b, c)', '"x, y"']`.
    Anything after the matching `)` is ignored; `[]` when there is no complete list. With `keep_empty` (C macro
    invocations, where an empty argument is positional) `MAC(a, , b)` -> `['a', '', 'b']`; `()` is still `[]`."""
    span = paren_span(text, lang)
    if span is None:
        return []
    inner = text[span[0] + 1:span[1]]
    if not keep_empty:
        return split_top(inner, lang, angle=angle)
    parts = [_join(p) for p in _split_tokens(_code_tokens(inner, lang), ",", angle)]
    return parts if any(parts) else []


def partition_top(text: str, lang: str | None = "c", op: str = "=", *, angle: bool = False) -> tuple[str, str | None]:
    """Split at the first top-level `op` token: `('sep: str = ","', "=")` -> `('sep: str', '","')`. The second
    part is None when `op` does not occur at depth 0 (an `=` inside a default literal or brackets does not count)."""
    toks = _code_tokens(text, lang)
    depth = 0
    for i, t in enumerate(toks):
        if t.kind == "op" and t.text == op and depth == 0:
            return _join(toks[:i]), _join(toks[i + 1:])
        depth = max(0, depth + _depth_step(t, angle))
    return _join(toks), None


def body_hash(text: bytes | str, lang: str | None = "c") -> str:
    """Content hash of a function body that ignores formatting (whitespace between tokens, comments) but
    not meaning (string literals verbatim, operator adjacency, Python indentation). See `tokenize`."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    norm = " ".join(tokenize(text, lang))
    return "sha1:" + hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()


@functools.lru_cache(maxsize=65536)
def realpath(path: str) -> str:
    """`os.path.realpath` with a cache: identity must not depend on how a path was spelled (review finding C4:
    a build's `src -> ../source` symlink gave the same file an absolute id)."""
    return os.path.realpath(path)


def rel(path: str, root: str) -> str:
    """Path relative to root when inside it (symlinks resolved on both sides), else the absolute real path
    (external/system files)."""
    path = realpath(path)
    root = realpath(root)
    try:
        r = os.path.relpath(path, root)
    except ValueError:  # different drive (Windows)
        return path
    if r.startswith(".."):
        return path
    return r.replace(os.sep, "/")


def fingerprint_types(records: dict[str, dict]) -> dict[str, str]:
    """Deterministic 8-hex fingerprints for a graph of type records (review round 7):
    `records[key] = {"identity": tuple, "local": JSON-able, "edges": [(label, target_key), …]}`.
    Strongly connected components (Tarjan) are processed dependencies first; a component is serialised once with
    its members in canonical `identity` order, internal edges written as member indexes and external edges as the
    target's fingerprint; every member's fingerprint derives from that one digest plus its index. So a fingerprint
    depends only on what is reachable from the type and on root-relative identities: self- and mutual recursion,
    unrelated types and declaration order cannot change it, and the same structure gets the same value in every TU."""
    import json as _json
    keys = list(records)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []
    counter = 0
    for root_key in keys:
        if root_key in index:
            continue
        work = [(root_key, iter(records[root_key].get("edges") or []))]
        index[root_key] = low[root_key] = counter
        counter += 1
        stack.append(root_key)
        on_stack.add(root_key)
        while work:
            v, it = work[-1]
            advanced = False
            for _label, w in it:
                if w not in records:
                    continue
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(records[w].get("edges") or [])))
                    advanced = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                sccs.append(comp)
    fp: dict[str, str] = {}
    for comp in sccs:                                   # Tarjan emits a component after everything it reaches
        members = sorted(comp, key=lambda k: _json.dumps(records[k].get("identity"), sort_keys=True, default=str))
        pos = {k: i for i, k in enumerate(members)}
        ser = []
        for k in members:
            r = records[k]
            edges = []
            for label, target in r.get("edges") or []:
                if target in pos:
                    edges.append([label, "internal", pos[target]])
                else:
                    edges.append([label, "external", fp.get(target, "missing")])
            ser.append([r.get("identity"), r.get("local"), edges])
        digest = hashlib.sha1(_json.dumps(ser, sort_keys=True, default=str).encode("utf-8", "replace")).hexdigest()
        for k in members:
            fp[k] = short_hash(f"{digest}:{pos[k]}")
    return fp


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
