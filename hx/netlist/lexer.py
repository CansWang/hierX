"""Physical lines -> logical statements with spans, and statement tokens. Role-free: every line is a statement
(the index applies the title rule), continuation lines are joined with per-piece spans, inline comments are stripped
per profile (never inside quotes or braces), `.control…​.endc` and `.prot…​.unprot` regions stay verbatim."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional

from .profiles import Profile


@dataclass
class RawStatement:
    file: str
    line: int
    end_line: int
    text: str                                  # logical text: pieces joined by one space, comments removed
    pieces: list[tuple[int, int, str]] = field(default_factory=list)   # (line, col, fragment) as written
    kind_hint: str = "element"                 # title | dot | element | control | encrypted | unparsed

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "RawStatement":
        return cls(file=d["file"], line=d["line"], end_line=d["end_line"], text=d["text"],
                   pieces=[tuple(p) for p in d.get("pieces", [])], kind_hint=d.get("kind_hint", "element"))


@dataclass
class Tok:
    kind: str          # name | number | expr | string | assign | punct | keyword
    text: str
    line: int
    col: int


def _strip_inline_comment(line: str, profile: Profile) -> str:
    """Cut the line at the first inline-comment marker that is outside quotes/braces and allowed by the guard."""
    if not profile.inline_comment:
        return line
    guard = re.compile(profile.inline_comment_guard)
    i, depth, quote = 0, 0, None
    opens = {o: c for o, c in profile.expr_delims if o != c}
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in profile.string_delims or any(o == c == ch for o, c in profile.expr_delims):
            quote = ch
            i += 1
            continue
        if ch in opens:
            depth += 1
        elif ch in opens.values():
            depth = max(0, depth - 1)
        elif depth == 0:
            for m in profile.inline_comment:
                if line.startswith(m, i) and (i == 0 or guard.match(line, i)):
                    nxt = line[i + len(m):i + len(m) + 1]
                    if m == "$" and (nxt.isalnum() or nxt in "_{"):
                        continue                     # `$G_1`-style names are not comments
                    return line[:i]
        i += 1
    return line


def read_statements(text: str, profile: Profile, file: str) -> list[RawStatement]:
    lines = text.splitlines()
    out: list[RawStatement] = []
    cur: Optional[RawStatement] = None
    i = 0
    n = len(lines)

    def flush():
        nonlocal cur
        if cur is not None:
            cur.text = " ".join(p[2] for p in cur.pieces).strip()
            out.append(cur)
            cur = None

    while i < n:
        raw = lines[i]
        lineno = i + 1
        stripped = raw.lstrip()
        col = len(raw) - len(stripped)
        if not stripped:
            i += 1                                   # a blank line never ends a continuation (ngspice joins `+` across it)
            continue
        low = stripped.lower()
        # verbatim regions: .control … .endc and .prot … .unprot
        region = None
        if low.startswith(".control"):
            region = ("control", (".endc",))
        elif low.startswith((".prot", ".protect")):
            region = ("encrypted", (".unprot", ".unprotect"))
        if region:
            flush()
            kind, closers = region
            j = i
            while j < n and not lines[j].lstrip().lower().startswith(closers):
                j += 1
            end = min(j, n - 1)
            block = "\n".join(lines[i:end + 1])
            out.append(RawStatement(file=file, line=lineno, end_line=end + 1, text=block,
                                    pieces=[(lineno, col, block)], kind_hint=kind))
            i = end + 1
            continue
        if stripped[0] in profile.line_comment:
            i += 1                                   # a comment line never ends a continuation
            continue
        if stripped[0] in profile.continuation:
            frag = _strip_inline_comment(stripped[1:].strip(), profile)
            if cur is None:
                out.append(RawStatement(file=file, line=lineno, end_line=lineno, text=frag,
                                        pieces=[(lineno, col + 1, frag)], kind_hint="unparsed"))
            else:
                cur.pieces.append((lineno, col + 1, frag))
                cur.end_line = lineno
            i += 1
            continue
        flush()
        frag = _strip_inline_comment(stripped, profile).rstrip()
        cur = RawStatement(file=file, line=lineno, end_line=lineno, text=frag, pieces=[(lineno, col, frag)],
                           kind_hint="dot" if frag.startswith(".") else "element")
        if frag.lower().startswith(".end") and not frag.lower().startswith((".ends", ".endl", ".endif", ".endc")):
            flush()
            break                                    # nothing after .end is part of the deck
        i += 1
    flush()
    return out


_NAME_START = re.compile(r"[A-Za-z0-9_$~!@#%^&*\-/\\.\[\]<>?]")


def tokenize(text: str, profile: Profile) -> list[Tok]:
    """`{…}` / `'…'` -> one expr token (nesting-aware for braces), `"…"` -> one string, `w=1u` -> name, assign, value,
    `PARAMS:` -> keyword, `(`/`)`/`,` -> punct (separators), everything else a name (numbers are names too: a net
    may be called `1`)."""
    toks: list[Tok] = []
    i, n, line, col0 = 0, len(text), 0, 0
    opens = dict(profile.expr_delims)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        start = i
        if ch in profile.string_delims:
            j = text.find(ch, i + 1)
            j = n - 1 if j < 0 else j
            toks.append(Tok("string", text[i:j + 1], line, start))
            i = j + 1
            continue
        if ch in opens:
            close = opens[ch]
            if close == ch:                           # quote-style expression delimiter
                j = text.find(ch, i + 1)
                j = n - 1 if j < 0 else j
            else:
                depth, j = 0, i
                while j < n:
                    if text[j] == ch:
                        depth += 1
                    elif text[j] == close:
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                j = min(j, n - 1)
            toks.append(Tok("expr", text[i:j + 1], line, start))
            i = j + 1
            continue
        if ch == "=":
            toks.append(Tok("assign", "=", line, start))
            i += 1
            continue
        if ch in "(),":
            toks.append(Tok("punct", ch, line, start))
            i += 1
            continue
        j = i
        while j < n and not text[j].isspace() and text[j] not in "=(),\"" and not (text[j] in opens and j > i):
            if text[j] == "'" and j > i:
                break
            j += 1
        word = text[i:j]
        if word.lower() == "params:":
            toks.append(Tok("keyword", word, line, start))
        elif word[0].isdigit() or (word[0] in "+-." and len(word) > 1 and word[1].isdigit()):
            toks.append(Tok("number", word, line, start))
        else:
            toks.append(Tok("name", word, line, start))
        i = j if j > i else i + 1
    return toks


def assignments(toks: list[Tok]) -> tuple[list[Tok], list[tuple[str, str]]]:
    """Split tokens into positional ones and `name=value` pairs (value = the token after `=`, expressions kept verbatim)."""
    positional, pairs, i = [], [], 0
    while i < len(toks):
        t = toks[i]
        if t.kind == "punct":
            i += 1
            continue
        if i + 2 < len(toks) + 1 and i + 1 < len(toks) and toks[i + 1].kind == "assign":
            val = toks[i + 2].text if i + 2 < len(toks) else ""
            pairs.append((t.text, val))
            i += 3
            continue
        if t.kind == "keyword":
            i += 1
            continue
        positional.append(t)
        i += 1
    return positional, pairs
