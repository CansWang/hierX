"""Grammar dispatch: a profile names its grammar; the resolver asks the grammar to split an element or a definition.
Phase 1 ships the SPICE family grammar (first-letter families); Spectre (master-name resolution) is Phase 3."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .lexer import Tok, assignments
from .profiles import Family, Profile


@dataclass
class ElementParts:
    name: str
    positional: list[str]                # terminal nets as written, in order
    master: Optional[str] = None         # model name (devices) or subcircuit name (X)
    value: Optional[str] = None
    params: list[tuple[str, str]] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


class Grammar:
    def split_element(self, toks: list[Tok], family: Optional[Family], is_model: Callable[[str], bool]) -> ElementParts:
        raise NotImplementedError

    def split_definition(self, toks: list[Tok]) -> tuple[str, list[str], list[tuple[str, str]]]:
        raise NotImplementedError


class SpiceGrammar(Grammar):
    """`<name> <terminal>+ [controlling ref]* [model] [value] [PARAMS:] [k=v]*`: terminals, then the family's
    controlling references (F/H/W: a source; K: two inductors), then the model (required families take the next token,
    variable-arity ones locate the token a scope lookup knows, so `q1 c b e 0 npnmod` and `q2 c b e npnmod` both
    resolve; optional-model families take the next token only when the scope knows it), then the value;
    `X<name> <node>+ <subckt> [PARAMS:] [k=v]*` (the subcircuit is the last positional token); `.subckt <name>
    <port>* [PARAMS:] [k=v]*`."""

    def split_definition(self, toks):
        positional, pairs = assignments(toks[1:])
        if not positional:
            return "", [], pairs
        return positional[0].text, [t.text for t in positional[1:]], pairs

    def split_element(self, toks, family, is_model):
        positional, pairs = assignments(toks)
        if not positional:
            return ElementParts(name="", positional=[], diagnostics=["empty element"])
        name = positional[0].text
        rest = [t.text for t in positional[1:]]
        parts = ElementParts(name=name, positional=[], params=pairs)
        if family is None:
            parts.positional = rest
            parts.diagnostics.append("unknown-device-family")
            return parts
        if family.terminals is None:                         # X: nets then the subcircuit name
            if not rest:
                parts.diagnostics.append("subcircuit instance without a definition name")
                return parts
            parts.master = rest[-1]
            parts.positional = rest[:-1]
            return parts
        lo, hi = family.min_terminals, family.max_terminals
        if family.refs and family.letter != "K":
            parts.positional = rest[:lo]
            parts.refs = rest[lo:lo + len(family.refs)]
            remaining = rest[lo + len(family.refs):]
            if len(parts.refs) < len(family.refs):
                parts.diagnostics.append("missing controlling reference")
        elif family.letter == "K":
            parts.refs = rest[:2]
            remaining = rest[2:]
            if len(parts.refs) < 2:
                parts.diagnostics.append("missing coupled inductor reference")
        if family.refs:                                       # the model (W: `w1 p n vsense sm`) follows the references
            if family.model == "required":
                if remaining:
                    parts.master = remaining[0]
                    remaining = remaining[1:]
                else:
                    parts.diagnostics.append("missing model")
            elif family.model == "optional" and remaining and is_model(remaining[0]):
                parts.master = remaining[0]
                remaining = remaining[1:]
        elif family.model == "required":
            found = None
            for i in range(lo, min(hi, len(rest) - 1) + 1):
                if i < len(rest) and is_model(rest[i]):
                    found = i
                    break
            if found is None:
                low = next((i for i in range(0, min(lo, len(rest))) if is_model(rest[i])), None)   # a model with too few nets
                if low is not None:
                    found = low
            if found is None:
                n = min(max(lo, len(rest) - 1), hi) if len(rest) > lo else len(rest)
                parts.positional = rest[:n]
                parts.master = rest[n] if n < len(rest) else None
                remaining = rest[n + 1:] if n < len(rest) else []
                parts.diagnostics.append("model-not-visible" if parts.master else "missing model")
            else:
                parts.positional = rest[:found]
                parts.master = rest[found]
                remaining = rest[found + 1:]
        elif family.model == "optional":
            parts.positional = rest[:lo]
            remaining = rest[lo:]
            if remaining and is_model(remaining[0]):
                parts.master = remaining[0]
                remaining = remaining[1:]
        elif family.letter in ("E", "G"):
            keyed = any(k.lower() in ("value", "vol", "cur", "poly", "table") for k, _ in pairs) or \
                any(r.lower() in ("value", "vol", "cur", "poly", "table") or r.lower().startswith(("poly(", "value=")) for r in rest[2:3])
            n = 2 if keyed or len(rest) < 4 else 4
            parts.positional = rest[:n]
            remaining = rest[n:]
        else:
            parts.positional = rest[:lo]
            remaining = rest[lo:]
        if len(parts.positional) < lo:
            parts.diagnostics.append(f"only {len(parts.positional)} of {lo} terminals")
        if family.value and remaining:
            parts.value = " ".join(remaining)
        elif remaining:
            parts.value = " ".join(remaining)
        return parts


GRAMMARS: dict[str, Grammar] = {"spice": SpiceGrammar()}


def grammar_for(profile: Profile) -> Grammar:
    try:
        return GRAMMARS[profile.grammar]
    except KeyError:
        from ..frontends.base import FrontendError
        raise FrontendError(f"grammar {profile.grammar!r} arrives in a later phase") from None
