"""Source-only Rust helpers. Semantic targets continue to come from rust-analyzer."""
from __future__ import annotations


def split_tokens(tokens, sep=",", *, types=False):
    """Split Rust types/expressions, distinguishing closure headers and turbofish from comparisons."""
    result, part = [], []
    brackets, angles, closure = 0, 0, False
    for i, tok in enumerate(tokens):
        s = tok.text
        prev = tokens[i - 1].text if i else ""
        if tok.kind == "op":
            if s == sep and not (brackets or angles or closure):
                result.append(part)
                part = []
                continue
            if s == "|" and not (brackets or angles):
                if closure:
                    closure = False
                elif not part or prev in ("move", "async", "static"):
                    closure = True
            if s in ("(", "[", "{"):
                brackets += 1
            elif s in (")", "]", "}"):
                brackets = max(0, brackets - 1)
            elif not brackets:
                if s == "<" and (types or angles or prev == "::" or any(t.text in ("->", "as") for t in part) or
                                  (not part and any(t.text == "as" for t in tokens[i + 1:]))):
                    angles += 1
                elif angles and s in (">", ">>"):
                    angles = max(0, angles - len(s))
        part.append(tok)
    result.append(part)
    return result


def impl_name(header):
    """Public scope for an impl header, including trait type arguments but excluding bounds."""
    from .ids import lex
    toks = lex(header, "rs")
    if not toks or toks[0].text != "impl":
        return header
    toks = toks[1:]
    if toks and toks[0].text == "<":
        depth, end = 0, 0
        for end, t in enumerate(toks):
            depth += 1 if t.text == "<" else (-len(t.text) if t.text in (">", ">>") else 0)
            if depth <= 0:
                break
        toks = toks[end + 1:]
    depth, split, stop = 0, None, len(toks)
    for i, t in enumerate(toks):
        if depth == 0 and t.text in ("where", "{"):
            stop = i
            break
        if depth == 0 and t.text == "for":
            split = i
        depth += 1 if t.text == "<" else (-len(t.text) if t.text in (">", ">>") else 0)
    def compact(ts):
        return "".join((" " if i and t.kind in ("ident", "number") and ts[i - 1].kind in ("ident", "number") else "") + t.text
                       for i, t in enumerate(ts))
    if split is None:
        return compact(toks[:stop])
    return f"<{compact(toks[split + 1:stop])} as {compact(toks[:split])}>"


def source_signature(source, name):
    """Fallback declaration header; never mistake a hover documentation example for its signature."""
    from .ids import lex
    toks = lex(source, "rs")
    start = next((i for i, t in enumerate(toks[:-1]) if t.text == "fn" and toks[i + 1].text == name), None)
    if start is None:
        return None
    brackets, angles = 0, 0
    for t in toks[start:]:
        if t.text in ("{", ";") and not (brackets or angles):
            return source[toks[start].start:t.start].strip()
        if t.text in ("(", "[", "{"):
            brackets += 1
        elif t.text in (")", "]", "}"):
            brackets -= 1
        elif not brackets and t.text == "<":
            angles += 1
        elif not brackets and t.text in (">", ">>"):
            angles = max(0, angles - len(t.text))
    return None
