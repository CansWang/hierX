"""Raw statements -> typed statements. `lex_file` is role-free (what the per-file cache stores); `structure` applies the
title rule BEFORE grouping scopes (a deck's first line is the title whatever it says; an include or library keeps
its line 1), then groups `.subckt/.ends`, `.if/.elseif/.else/.endif` and `.lib name/.endl`."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .lexer import RawStatement, Tok, read_statements, tokenize, assignments
from .profiles import Profile


@dataclass
class RawFile:
    path: str
    statements: list[RawStatement]

    def to_json(self) -> dict:
        return {"path": self.path, "statements": [s.to_json() for s in self.statements]}

    @classmethod
    def from_json(cls, d: dict) -> "RawFile":
        return cls(path=d["path"], statements=[RawStatement.from_json(s) for s in d["statements"]])


def lex_file(path: str, profile: Profile, text: Optional[str] = None) -> RawFile:
    if text is None:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    return RawFile(path=path, statements=read_statements(text, profile, path))


# ---------------------------------------------------------------- typed statements

@dataclass
class Stmt:
    raw: RawStatement

    @property
    def text(self) -> str:
        return self.raw.text

    @property
    def line(self) -> int:
        return self.raw.line

    @property
    def end_line(self) -> int:
        return self.raw.end_line

    @property
    def file(self) -> str:
        return self.raw.file


@dataclass
class Title(Stmt):
    title: str = ""


@dataclass
class Element(Stmt):
    letter: str = ""
    name: str = ""                       # spelled
    family_known: bool = True
    _toks: Optional[list[Tok]] = None

    def tokens(self, profile: Profile) -> list[Tok]:
        if self._toks is None:
            self._toks = tokenize(self.text, profile)
        return self._toks


@dataclass
class SubcktDef(Stmt):
    name: str = ""                       # spelled
    ports: list[str] = field(default_factory=list)
    params: list[tuple[str, str]] = field(default_factory=list)
    body: list[Stmt] = field(default_factory=list)
    end_raw: Optional[RawStatement] = None


@dataclass
class Include(Stmt):
    path_text: str = ""


@dataclass
class LibRef(Stmt):
    path_text: str = ""
    section: str = ""


@dataclass
class LibSection(Stmt):
    name: str = ""
    body: list[Stmt] = field(default_factory=list)
    end_raw: Optional[RawStatement] = None   # the .endl statement (the section's span ends there)

    @property
    def span_end(self) -> int:
        return self.end_raw.end_line if self.end_raw else max([self.end_line] + [s.end_line for s in self.body])


@dataclass
class ParamStmt(Stmt):
    assignments: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ModelStmt(Stmt):
    name: str = ""
    type: str = ""
    params_text: str = ""


@dataclass
class GlobalStmt(Stmt):
    names: list[str] = field(default_factory=list)


@dataclass
class Conditional(Stmt):
    branches: list[tuple[str, list[Stmt]]] = field(default_factory=list)   # (condition text, body); the else branch has condition ""
    has_else: bool = False


@dataclass
class ControlBlock(Stmt):
    pass


@dataclass
class Encrypted(Stmt):
    pass


@dataclass
class Directive(Stmt):
    name: str = ""
    role: str = "unknown"


@dataclass
class EndStmt(Stmt):
    pass


@dataclass
class Unparsed(Stmt):
    reason: str = ""


@dataclass
class FileSummary:
    file: str
    role: str
    statements: list[Stmt]
    diagnostics: list[dict] = field(default_factory=list)
    title: Optional[str] = None


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _diag(out: list[dict], code: str, message: str, raw: RawStatement, severity: str = "error") -> None:
    out.append({"severity": severity, "code": code, "message": message, "file": raw.file, "line": raw.line})


def structure(raw: RawFile, role: str, profile: Profile) -> FileSummary:
    stmts = raw.statements
    diags: list[dict] = []
    title: Optional[str] = None
    out: list[Stmt] = []
    # frames: (kind, header statement, current body list, extra)
    frames: list[tuple[str, object, list[Stmt], dict]] = [("top", None, out, {})]
    start = 0
    if role == "deck" and profile.title_line:
        if stmts and stmts[0].line == 1:
            title = stmts[0].text
            out.append(Title(raw=stmts[0], title=title))
            start = 1
            if title.startswith("."):
                _diag(diags, "title-is-directive", f"line 1 {title!r} is the title (a deck's first line is never a statement); "
                      "address a library as `file:@name` without --deck or include it from a deck", stmts[0], "warning")
        else:
            title = ""
    for rs in stmts[start:]:
        body = frames[-1][2]
        if rs.kind_hint == "control":
            body.append(ControlBlock(raw=rs))
            continue
        if rs.kind_hint == "encrypted":
            body.append(Encrypted(raw=rs))
            _diag(diags, "encrypted-content", f"protected region at {rs.file}:{rs.line}-{rs.end_line}; declarations inside are invisible", rs, "warning")
            continue
        if rs.kind_hint == "unparsed":
            body.append(Unparsed(raw=rs, reason="continuation line without a statement"))
            _diag(diags, "unparsed-statement", "continuation line without a statement", rs)
            continue
        text = rs.text
        if not text:
            continue
        if text.startswith("."):
            toks = tokenize(text, profile)
            word = toks[0].text.lower() if toks else text.lower()
            d = profile.directives.get(word)
            drole = d.role if d else "unknown"
            positional, pairs = assignments(toks[1:])
            if drole == "scope_open":
                if not positional:
                    body.append(Unparsed(raw=rs, reason=".subckt without a name"))
                    _diag(diags, "unparsed-statement", ".subckt without a name", rs)
                    continue
                sd = SubcktDef(raw=rs, name=positional[0].text, ports=[t.text for t in positional[1:]], params=pairs)
                frames.append(("subckt", sd, sd.body, {}))
            elif drole == "scope_close":
                if frames[-1][0] != "subckt":
                    _diag(diags, "unparsed-statement", ".ends without an open .subckt", rs)
                    body.append(Unparsed(raw=rs, reason=".ends without an open .subckt"))
                    continue
                _k, sd, _b, _x = frames.pop()
                if positional and profile and (positional[0].text.lower() if not profile.case_sensitive else positional[0].text) != \
                        (sd.name.lower() if not profile.case_sensitive else sd.name):
                    _diag(diags, "ends-name-mismatch", f".ends {positional[0].text} closes .subckt {sd.name}", rs, "warning")
                sd.end_raw = rs
                frames[-1][2].append(sd)
            elif drole == "cond_if":
                cond = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
                c = Conditional(raw=rs, branches=[(cond, [])])
                frames.append(("cond", c, c.branches[0][1], {}))
            elif drole == "cond_elseif":
                if frames[-1][0] != "cond":
                    _diag(diags, "unparsed-statement", ".elseif without .if", rs)
                    body.append(Unparsed(raw=rs, reason=".elseif without .if"))
                    continue
                c = frames[-1][1]
                cond = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
                c.branches.append((cond, []))
                frames[-1] = ("cond", c, c.branches[-1][1], {})
            elif drole == "cond_else":
                if frames[-1][0] != "cond":
                    _diag(diags, "unparsed-statement", ".else without .if", rs)
                    body.append(Unparsed(raw=rs, reason=".else without .if"))
                    continue
                c = frames[-1][1]
                c.branches.append(("", []))
                c.has_else = True
                frames[-1] = ("cond", c, c.branches[-1][1], {})
            elif drole == "cond_end":
                if frames[-1][0] != "cond":
                    _diag(diags, "unparsed-statement", ".endif without .if", rs)
                    body.append(Unparsed(raw=rs, reason=".endif without .if"))
                    continue
                _k, c, _b, _x = frames.pop()
                frames[-1][2].append(c)
            elif drole == "lib":
                if len(positional) >= 2:
                    body.append(LibRef(raw=rs, path_text=_unquote(positional[0].text), section=positional[1].text))
                elif len(positional) == 1:
                    ls = LibSection(raw=rs, name=positional[0].text)
                    frames.append(("lib", ls, ls.body, {}))
                else:
                    body.append(Unparsed(raw=rs, reason=".lib without arguments"))
                    _diag(diags, "unparsed-statement", ".lib without arguments", rs)
            elif drole == "lib_end":
                if frames[-1][0] != "lib":
                    _diag(diags, "unparsed-statement", ".endl without .lib section", rs, "warning")
                    continue
                _k, ls, _b, _x = frames.pop()
                ls.end_raw = rs
                frames[-1][2].append(ls)
            elif drole == "include":
                if not positional:
                    body.append(Unparsed(raw=rs, reason=".include without a path"))
                    _diag(diags, "unparsed-statement", ".include without a path", rs)
                    continue
                body.append(Include(raw=rs, path_text=_unquote(positional[0].text)))
            elif drole == "param":
                body.append(ParamStmt(raw=rs, assignments=pairs))
            elif drole == "global":
                body.append(GlobalStmt(raw=rs, names=[t.text for t in positional]))
            elif drole == "model":
                if len(positional) < 2:
                    body.append(Unparsed(raw=rs, reason=".model needs a name and a type"))
                    _diag(diags, "unparsed-statement", ".model needs a name and a type", rs)
                    continue
                rest = text.split(None, 3)
                body.append(ModelStmt(raw=rs, name=positional[0].text, type=positional[1].text,
                                      params_text=rest[3] if len(rest) > 3 else ""))
            elif drole == "end":
                body.append(EndStmt(raw=rs))
            elif drole == "title":
                title = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
                body.append(Directive(raw=rs, name=word, role="title"))
            else:
                body.append(Directive(raw=rs, name=word, role=drole))
                if drole == "unknown":
                    _diag(diags, "unsupported-directive", f"{word} is not understood; kept as text", rs, "warning")
            continue
        letter = text[0].upper()
        name = text.split(None, 1)[0]
        fam_known = letter in profile.families
        body.append(Element(raw=rs, letter=letter, name=name, family_known=fam_known))
    while len(frames) > 1:
        kind, hdr, _b, _x = frames.pop()
        if kind == "subckt":
            _diag(diags, "unparsed-statement", f".subckt {hdr.name} never closed", hdr.raw)
        elif kind == "cond":
            _diag(diags, "unparsed-statement", ".if never closed", hdr.raw)
        elif kind == "lib":
            _diag(diags, "unparsed-statement", f".lib {hdr.name} never closed", hdr.raw)
        frames[-1][2].append(hdr)
    return FileSummary(file=raw.path, role=role, statements=out, diagnostics=diags, title=title)
