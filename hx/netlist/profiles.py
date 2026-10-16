"""Dialect profiles: DATA tables only. A profile names the grammar (statement syntax family) it uses; everything a
dialect changes (comment markers, continuation, expression delimiters, device families, directive roles) is a value in
these tables, so `NGSPICE` is `replace(SPICE, …)` and a test asserts the two differ only in data."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Optional


@dataclass(frozen=True)
class Family:
    letter: str
    element: str
    terminals: Optional[tuple[str, ...]]     # None: from the subcircuit definition (X)
    min_terminals: int
    max_terminals: int
    model: str = "none"                      # required | optional | none
    value: bool = False                      # a value/expression follows the nets (R, C, V, …)
    refs: tuple[str, ...] = ()               # controlling references by role, in positional order (F/H: vsource; K: inductor×2)


@dataclass(frozen=True)
class Directive:
    name: str
    role: str                                # see ROLES


ROLES = ("scope_open", "scope_close", "include", "lib", "lib_end", "param", "global", "model", "cond_if", "cond_elseif",
         "cond_else", "cond_end", "control", "control_end", "end", "analysis", "option", "output", "func", "protect",
         "unprotect", "title", "unknown")


@dataclass(frozen=True)
class Profile:
    name: str
    grammar: str = "spice"                   # spice | spectre (Phase 3)
    case_sensitive: bool = False
    title_line: bool = True                  # the deck's first line is a title, whatever it says
    line_comment: tuple[str, ...] = ("*",)
    inline_comment: tuple[str, ...] = ()
    inline_comment_guard: str = r"(?<=\s)"  # a marker counts only here (never inside quotes or braces); `$` also needs a non-name follower
    continuation: tuple[str, ...] = ("+",)
    expr_delims: tuple[tuple[str, str], ...] = (("{", "}"), ("'", "'"))
    string_delims: tuple[str, ...] = ('"',)
    families: dict[str, Family] = field(default_factory=dict)
    directives: dict[str, Directive] = field(default_factory=dict)
    ground_names: tuple[str, ...] = ("0", "gnd")
    duplicate_definition: str = "ambiguous"  # same-scope duplicates are never last-wins
    scope_sep: str = "."


def _fam(letter, element, terminals, lo, hi, model="none", value=False, refs=()):
    return Family(letter, element, tuple(terminals) if terminals is not None else None, lo, hi, model, value, tuple(refs))


SPICE_FAMILIES = {f.letter: f for f in (
    _fam("R", "resistor", ("p", "n"), 2, 2, "optional", True),
    _fam("C", "capacitor", ("p", "n"), 2, 2, "optional", True),
    _fam("L", "inductor", ("p", "n"), 2, 2, "optional", True),
    _fam("D", "diode", ("a", "c"), 2, 2, "required"),
    _fam("Q", "bjt", ("c", "b", "e", "s"), 3, 4, "required"),
    _fam("M", "mosfet", ("d", "g", "s", "b"), 4, 7, "required"),
    _fam("J", "jfet", ("d", "g", "s"), 3, 3, "required"),
    _fam("Z", "mesfet", ("d", "g", "s"), 3, 3, "required"),
    _fam("N", "osdi", tuple(f"t{i}" for i in range(1, 9)), 2, 8, "required"),   # compiled Verilog-A (OSDI) model: layout unknown, named positionally
    _fam("V", "vsource", ("p", "n"), 2, 2, "none", True),
    _fam("I", "isource", ("p", "n"), 2, 2, "none", True),
    _fam("E", "vcvs", ("p", "n", "cp", "cn"), 2, 4, "none", True),
    _fam("G", "vccs", ("p", "n", "cp", "cn"), 2, 4, "none", True),
    _fam("F", "cccs", ("p", "n"), 2, 2, "none", True, ("vsource",)),
    _fam("H", "ccvs", ("p", "n"), 2, 2, "none", True, ("vsource",)),
    _fam("K", "coupling", (), 0, 0, "none", True, ("inductor", "inductor")),
    _fam("S", "vswitch", ("p", "n", "cp", "cn"), 4, 4, "required"),
    _fam("W", "iswitch", ("p", "n"), 2, 2, "required", False, ("vsource",)),
    _fam("B", "behavioral", ("p", "n"), 2, 2, "none", True),
    _fam("T", "tline", ("p1", "n1", "p2", "n2"), 4, 4, "optional", True),
    _fam("O", "ltline", ("p1", "n1", "p2", "n2"), 4, 4, "required"),
    _fam("U", "urc", ("p1", "p2", "n"), 3, 3, "required"),
    _fam("X", "subcircuit", None, 0, 10 ** 6, "none"),
)}

_SPICE_DIRECTIVES = {
    ".subckt": "scope_open", ".ends": "scope_close", ".include": "include", ".inc": "include", ".lib": "lib", ".endl": "lib_end",
    ".param": "param", ".global": "global", ".model": "model", ".end": "end", ".title": "title",
    ".op": "analysis", ".dc": "analysis", ".ac": "analysis", ".tran": "analysis", ".noise": "analysis", ".tf": "analysis",
    ".disto": "analysis", ".pz": "analysis", ".sens": "analysis", ".four": "analysis", ".pss": "analysis", ".sp": "analysis",
    ".option": "option", ".options": "option", ".opt": "option", ".temp": "option", ".ic": "option", ".nodeset": "option",
    ".print": "output", ".plot": "output", ".save": "output", ".probe": "output", ".width": "output",
    ".measure": "output", ".meas": "output",
    ".func": "func", ".prot": "protect", ".protect": "protect", ".unprot": "unprotect", ".unprotect": "unprotect",
}
SPICE_DIRECTIVES = {k: Directive(k, v) for k, v in _SPICE_DIRECTIVES.items()}

SPICE = Profile(name="spice", families=SPICE_FAMILIES, directives=SPICE_DIRECTIVES)

NGSPICE = replace(
    SPICE, name="ngspice", inline_comment=("$", ";", "//"),
    directives={**SPICE_DIRECTIVES, **{k: Directive(k, v) for k, v in {
        ".if": "cond_if", ".elseif": "cond_elseif", ".else": "cond_else", ".endif": "cond_end",
        ".control": "control", ".endc": "control_end", ".csparam": "param"}.items()}},
)

PROFILES: dict[str, Profile] = {"spice": SPICE, "ngspice": NGSPICE}
LATER_DIALECTS = ("hspice", "xyce", "spectre")      # named in --dialect help, refused until their phase lands

_CONTROL_RE = re.compile(r"^\s*\.(control|endc|if|elseif|endif|csparam)\b", re.I | re.M)
_SPECTRE_RE = re.compile(r"^\s*simulator\s+lang\s*=", re.I | re.M)


def sniff_dialect(text: str) -> str:
    """`.control`/`.endc`, `.if`/`.endif` or `.csparam` → ngspice; a Spectre language switch → 'spectre' (refused by
    the caller in Phase 1); otherwise plain spice."""
    if _SPECTRE_RE.search(text):
        return "spectre"
    if _CONTROL_RE.search(text):
        return "ngspice"
    return "spice"


def get_profile(name: str, text: str = "") -> Profile:
    """Resolve `--dialect` (auto|spice|ngspice|…); a dialect of a later phase raises a clear error."""
    from ..frontends.base import FrontendError
    if name == "auto":
        name = sniff_dialect(text)
    if name in PROFILES:
        return PROFILES[name]
    if name in LATER_DIALECTS:
        raise FrontendError(f"dialect {name!r} arrives in a later phase; Phase 1 supports --dialect spice|ngspice")
    raise FrontendError(f"unknown dialect {name!r}; choose from auto, {', '.join(PROFILES)}")
