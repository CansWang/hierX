"""ngspice as an OPTIONAL structural oracle: ngspice reads hx's own rendered include closure (search-path includes and
selected library sections inlined, every `.control` block and every analysis stripped) and prints `listing expand`;
hx's unguarded devices are compared on paths, arity, nets, models and controlling references. Guarded hx
occurrences are never compared (ngspice lists the active branch only) and the listing rows they could spell are
removed from the residual check. Values are never compared (ngspice evaluates them)."""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from .. import ids as _ids
from .grammar import SpiceGrammar
from .index import DesignIndex
from .lexer import tokenize
from .names import fold
from .parser import (Conditional, ControlBlock, Directive, Element, Encrypted, EndStmt, GlobalStmt, Include, LibRef, LibSection,
                     ModelStmt, ParamStmt, SubcktDef, Title, Unparsed)
from .profiles import Profile

_ROW = re.compile(r"^\s*(\d+)\s*:\s*(.*)$")
_SKIP_ROLES = ("analysis", "output", "control", "control_end")


# ------------------------------------------------------------ render
def render_closure(index: DesignIndex) -> str:
    """One deck from hx's resolution: includes replaced in place by what they resolved to, selected sections only,
    no `.control` blocks (anywhere), no analyses, `.end` last."""
    out: list[str] = [index.title or "hx oracle render"]
    deck = index.load(index.deck, index.root_role)

    def emit(stmts, file: str) -> None:
        for st in stmts:
            if isinstance(st, Title) or isinstance(st, EndStmt) or isinstance(st, ControlBlock) or isinstance(st, LibSection):
                continue
            if isinstance(st, SubcktDef):
                out.append(st.text)
                emit(st.body, file)
                out.append(st.end_raw.text if st.end_raw else ".ends")
                continue
            if isinstance(st, Include):
                path = index.resolution.get((file, st.line))
                if path is None:
                    out.append(st.text)
                    continue
                out.append(f"* hx: {st.text} -> {index._rel(path)}")
                emit(index.load(path, "include").statements, path)
                continue
            if isinstance(st, LibRef):
                path = index.resolution.get((file, st.line))
                if path is None:
                    out.append(st.text)
                    continue
                want = fold(st.section, index.profile.case_sensitive)
                out.append(f"* hx: {st.text} -> {index._rel(path)} section {st.section}")
                for sec in index.load(path, "library").statements:
                    if isinstance(sec, LibSection) and fold(sec.name, index.profile.case_sensitive) == want:
                        emit(sec.body, path)
                continue
            if isinstance(st, Conditional):
                for i, (cond, body) in enumerate(st.branches):
                    out.append((".if " + cond) if i == 0 else ((".elseif " + cond) if cond else ".else"))
                    emit(body, file)
                out.append(".endif")
                continue
            if isinstance(st, Directive) and st.role in _SKIP_ROLES:
                continue
            if isinstance(st, Encrypted):
                out.append(st.text)
                continue
            out.append(st.text)
    emit(deck.statements, index.deck)
    out += [".control", "listing expand", "quit", ".endc", ".end", ""]
    return "\n".join(out)


# ------------------------------------------------------------ run and parse
@dataclass
class Row:
    line: int
    text: str
    tokens: list[str]


@dataclass
class Listing:
    title: Optional[str] = None
    devices: list[Row] = field(default_factory=list)
    models: dict[str, Row] = field(default_factory=dict)       # listing model name (possibly `inst:name`) -> row
    directives: list[Row] = field(default_factory=list)


def run_ngspice(exe: str, render: str, cwd: str, timeout: float = 120.0) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "DISPLAY"}
    return subprocess.run([exe, "-n", "-b"], input=render, text=True, capture_output=True, cwd=cwd, env=env, timeout=timeout)


def parse_listing(stdout: str) -> Listing:
    lst = Listing()
    for line in stdout.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        no, text = int(m.group(1)), m.group(2).strip()
        toks = text.split()
        if no == 1 and lst.title is None:
            lst.title = text                                   # the title row, whatever its text
            continue
        if not toks:
            continue
        if toks[0].startswith("."):
            row = Row(no, text, toks)
            if toks[0].lower() == ".model" and len(toks) >= 2:
                lst.models[toks[1].lower()] = row
            elif toks[0].lower() == ".end":
                break
            else:
                lst.directives.append(row)
            continue
        lst.devices.append(Row(no, text, toks))
    return lst


# ------------------------------------------------------------ names
def ngspice_name(letter: str, segments: list[str], local_flags: list[bool], device: str) -> str:
    """ngspice's expanded name from the declaration context: a level whose instance's definition is LOCAL wraps
    `letter.inst.` around the current name; consecutive GLOBAL levels flatten under one `letter.` prefix
    (`c.xa.c.xh.c1`, `r.xb.xh.r1`, `r.xo.xm.xg.r.xl.r1`)."""
    name = device.lower()
    letter = letter.lower()
    i = len(segments) - 1
    while i >= 0:
        if local_flags[i]:
            name = f"{letter}.{segments[i]}.{name}"
            i -= 1
        else:
            j = i
            while j >= 0 and not local_flags[j]:
                j -= 1
            name = f"{letter}." + ".".join(segments[j + 1:i + 1]) + "." + name
            i = j
    return name


def strip_letters(name: str) -> tuple[list[str], str]:
    """Tolerant decode: drop single-letter tokens → (instance segments, device name)."""
    toks = [t for t in name.lower().split(".") if len(t) != 1 or not t.isalpha()]
    return toks[:-1], toks[-1] if toks else ""


def listing_split(row: Row, family, is_model):
    parts = SpiceGrammar().split_element(tokenize(row.text, _PLAIN), family, is_model)
    return parts


from .profiles import SPICE as _PLAIN  # noqa: E402  (listing rows carry no comments; plain tokens suffice)


# ------------------------------------------------------------ compare
@dataclass
class HxDevice:
    node_id: str
    letter: str
    name: str                      # device name (spelled)
    segments: list[str]            # instance path segments (folded)
    local_flags: list[bool]
    guarded: bool
    terminals: list[str]           # canonical nets in ngspice spelling
    model: Optional[str]           # folded model name or bin family base
    model_scope_prefix: Optional[str]   # instance path where the model was declared ('' = global)
    refs: list[str]                # expected ngspice names of controlling targets
    family: object = None


def compare(devices: list[HxDevice], listing: Listing, profile: Profile, hx_models: set[str], subtree: Optional[list[str]] = None) -> dict:
    """Project hx's unguarded devices onto the listing and diff paths, arity, nets, models and references."""
    by_name: dict[str, HxDevice] = {}
    guarded_spellings: set[str] = set()
    out_of_scope_hx = 0
    if subtree is not None:                                    # both sides are restricted to the subtree
        inside = [d for d in devices if d.segments[:len(subtree)] == subtree]
        out_of_scope_hx = len(devices) - len(inside)
        devices = inside
    for d in devices:
        spell = ngspice_name(d.letter, d.segments, d.local_flags, d.name)
        if d.guarded:
            guarded_spellings.add(spell)
            continue
        by_name[spell] = d
    model_names = {k.split(":")[-1] for k in listing.models} | hx_models
    is_model = lambda tok: tok.lower().split(":")[-1] in model_names
    mismatches: list[dict] = []
    matched: set[str] = set()
    guarded_sim = 0
    out_of_scope = 0
    name_form = 0
    rows_by_name: dict[str, Row] = {}
    for row in listing.devices:
        nm = row.tokens[0].lower()
        if subtree is not None:
            segs, _dev = strip_letters(nm)
            if segs[:len(subtree)] != subtree:
                out_of_scope += 1
                continue
        if nm in guarded_spellings:
            guarded_sim += 1
            continue
        rows_by_name[nm] = row
    for spell, d in by_name.items():
        row = rows_by_name.pop(spell, None)
        form = "exact"
        if row is None:
            want = (d.segments, d.name.lower())
            cand = [n for n in rows_by_name if strip_letters(n) == want]
            if len(cand) == 1:
                row = rows_by_name.pop(cand[0])
                form = "tolerant"
                name_form += 1
                mismatches.append({"path": spell, "what": "name-form", "terminal": None, "hx": spell, "ngspice": cand[0]})
        if row is None:
            mismatches.append({"path": spell, "what": "missing-in-ngspice", "terminal": None, "hx": spell, "ngspice": None})
            continue
        matched.add(spell)
        parts = listing_split(row, d.family, is_model)
        nets = [t.lower() for t in parts.positional]
        if len(nets) != len(d.terminals):
            mismatches.append({"path": spell, "what": "arity", "terminal": None, "hx": len(d.terminals), "ngspice": len(nets)})
        for i, (hn, ln) in enumerate(zip(d.terminals, nets)):
            if hn.lower() != ln:
                mismatches.append({"path": spell, "what": "net", "terminal": i, "hx": hn, "ngspice": ln})
        lm = (parts.master or "").lower()
        required = getattr(d.family, "model", "none") == "required"
        if d.model is not None or required:
            # a family that needs a model is always compared: a missing model on either side can never agree
            if d.model is None or not lm:
                mismatches.append({"path": spell, "what": "model", "terminal": None, "hx": d.model, "ngspice": lm or None})
            else:
                base = lm.split(":")[-1]
                prefix = lm.split(":")[0] if ":" in lm else ""
                if base != d.model.lower():
                    mismatches.append({"path": spell, "what": "model", "terminal": None, "hx": d.model, "ngspice": lm})
                elif d.model_scope_prefix is not None and prefix != d.model_scope_prefix:
                    mismatches.append({"path": spell, "what": "model", "terminal": "scope", "hx": d.model_scope_prefix, "ngspice": prefix})
        lrefs = [r.lower() for r in parts.refs]
        for i, (hr, lr) in enumerate(zip(d.refs, lrefs)):
            if hr != lr and strip_letters(hr) != strip_letters(lr):
                mismatches.append({"path": spell, "what": "ref", "terminal": i, "hx": hr, "ngspice": lr})
        if len(lrefs) != len(d.refs):
            mismatches.append({"path": spell, "what": "ref", "terminal": None, "hx": len(d.refs), "ngspice": len(lrefs)})
    for nm in rows_by_name:
        mismatches.append({"path": nm, "what": "missing-in-hx", "terminal": None, "hx": None, "ngspice": nm})
    summary = {"compared": len(matched), "guarded_hx": sum(1 for d in devices if d.guarded), "guarded_sim": guarded_sim,
               "unmatched": len([m for m in mismatches if m["what"] in ("missing-in-hx", "missing-in-ngspice")]),
               "name_form": name_form, "out_of_scope": out_of_scope, "out_of_scope_hx": out_of_scope_hx,
               "mismatches": len(mismatches), "agree": not mismatches}
    return {"summary": summary, "mismatches": mismatches}
