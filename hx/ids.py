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

import hashlib
import os
import re
from collections import defaultdict

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


def tokenize(text: str, lang: str | None = "c") -> list[str]:
    """Split a function body into tokens for hashing. What is kept and what is dropped:
    kept   identifiers, numbers, operators (maximal munch), string/char literals VERBATIM (their inner whitespace counts),
           and for Python the indentation of every logical line (relative to the first line; tabs count as 8)
    dropped comments (//, /* */, Python #), all other whitespace, blank lines, Python line continuations."""
    mode = _lang_mode(lang)
    py, rs, sv = mode == "py", mode == "rs", mode == "sv"
    out: list[str] = []
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
                out.append(f"\\n{max(0, ind - (base_indent or 0))}")
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
            tok = text[start:i]
            if out and last_end == start and (py and _PY_STR_PREFIX.match(out[-1])):
                tok = out.pop() + tok
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
                tok = text[i:j]
                if out and last_end == start and out[-1][0].isdigit():
                    tok = out.pop() + tok
                out.append(tok)
                i = last_end = j
                continue
            if rs and not (i + 1 < n and text[i + 1] == "\\") and not (i + 2 < n and text[i + 2] == "'"):
                j = i + 1   # lifetime 'a
                while j < n and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                out.append(text[i:j])
                i = last_end = j
                continue
            i = scan_quoted(i + 1, "'", multiline=False)
            if i - start > 24:        # not a char literal after all (e.g. an unbalanced quote in a macro): plain operator
                i = start + 1
            out.append(text[start:i])
            last_end = i
            continue
        # ---- words (identifiers, keywords) incl. prefixed/raw string literals
        if ch.isalpha() or ch in "_$":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            word = text[i:j]
            if j < n and text[j] == '"' and mode == "c" and word in _C_RAW_PREFIX:          # R"delim( ... )delim"
                lp = text.find("(", j)
                delim = text[j + 1:lp] if lp > 0 else ""
                close = text.find(")" + delim + '"', lp if lp > 0 else j)
                j = n if close < 0 else close + len(delim) + 2
                word = text[i:j]
            elif rs and word in ("r", "br") and j < n and text[j] in '#"':                 # r#"..."#
                k = j
                while k < n and text[k] == "#":
                    k += 1
                hashes = k - j
                if k < n and text[k] == '"':
                    close = text.find('"' + "#" * hashes, k + 1)
                    j = n if close < 0 else close + 1 + hashes
                    word = text[i:j]
            out.append(word)
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
            out.append(text[i:j])
            i = last_end = j
            continue
        # ---- operators / punctuation
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        for op in _MULTI_OPS:
            if text.startswith(op, i):
                out.append(op)
                i += len(op)
                break
        else:
            out.append(ch)
            i += 1
        last_end = i
    return out


def body_hash(text: bytes | str, lang: str | None = "c") -> str:
    """Content hash of a function body that ignores formatting (whitespace between tokens, comments) but
    not meaning (string literals verbatim, operator adjacency, Python indentation). See `tokenize`."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    norm = " ".join(tokenize(text, lang))
    return "sha1:" + hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()


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
