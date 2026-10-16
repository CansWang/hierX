"""SystemVerilog / Verilog frontend built on `verilator --xml-only`.

Verilator elaborates the design and dumps an XML AST. We map it to the IR:
  node kind `module`    the top cell (entry)                    id sv:<def file>::top
  node kind `instance`  every cell in the hierarchy             id sv:<def file>::top.u_core.u_alu
  node kind `function`/`task`  module- and package-level routines  id sv:<def file>::core.saturate
  params                ports (dir explicit: input→in, output→out, inout→inout); parameters go to attrs
  edges                 parent→child `instance` (args = port connections as written), routine calls `call`
  types                 typetable structs/unions/enums/typedef aliases; sizes and offsets are in BITS
Parameter specializations (`core__W10`) collapse onto the original module name for ids; the
specialization name and parameter values are kept in node.attrs. Types declared inside a module are identified by
their layout (`struct fp.fp_t@<fingerprint>`), package types by name; anonymous types by their first declaring
context. Generate-array paths use source spelling (`gen_lane[0].u_lane`). Values wider than 2**53 are canonical
strings (hx/values.py). Cache identity covers the expanded argument files and the engine version.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from typing import Optional

import hashlib

from .. import ids as _ids
from .. import values as _values
from ..cache import TUCache
from ..graphio import decode_verilator_name
from ..model import Loc, Node, Param, TypeUse, GlobalRefs, TypeDef, Field, Enumerator, GlobalVar
from .base import Frontend, FunctionRecord, DeclRecord, TypeRecord, CallSite, EntryNotFound, FrontendError

SUMMARY_VERSION = 3   # part of the cache key: bump when the index format, id or hashing rules change

SV_EXT = {".sv", ".svh", ".v", ".vh", ".verilog"}
DIR_MAP = {"input": "in", "output": "out", "inout": "inout", "in": "in", "out": "out", "ref": "inout"}
_CONST_RE = re.compile(r"^(?:(\d+)'s?([bodh]))?([0-9a-fA-F_xXzZ?]+)$")
_VAR_RE = re.compile(r"\$\{(\w+)\}|\$\((\w+)\)|\$(\w+)")
_WARN_RE = re.compile(r"^%Warning-(\w+):\s*(?:(\S+?):(\d+):(?:(\d+):)?\s*)?(.*)$")
_engine_cache: dict[str, str] = {}


def _is_implicit_name(name: str) -> bool:
    """Verilator invents `__typeimp…` names for anonymous (inline) struct/union/enum types; they renumber when
    declarations move, so hx treats them as anonymous and names the type by its declaring context (H6)."""
    return "__typeimp" in (name or "")


def expand_vars(text: str) -> str:
    """The three environment-variable spellings Verilator accepts in argument files: $VAR, ${VAR}, $(VAR)."""
    return _VAR_RE.sub(lambda m: os.environ.get(m.group(1) or m.group(2) or m.group(3), m.group(0)), text)


def filelist_fingerprints(path: str, root: str, via_F: bool = False, _seen: Optional[set] = None) -> list[tuple[str, str]]:
    """[(abs path, sha1 of the EXPANDED text)] for an argument file and every file it pulls in, following
    Verilator's resolution rules: a file reached through -f resolves relative paths inside it against the working
    directory (root); one reached through -F resolves them against its own directory; that context also decides
    where a nested -f/-F directive's file name is looked up, after which the nested file follows its own flag."""
    seen = _seen if _seen is not None else set()
    path = os.path.abspath(path)
    if path in seen:
        return []
    seen.add(path)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return [(path, "missing")]
    text = expand_vars(raw)
    out = [(path, hashlib.sha1(text.encode("utf-8", "replace")).hexdigest())]
    ctx = os.path.dirname(path) if via_F else root
    toks = [t for t in text.split() if t and not t.startswith(("//", "#"))]
    i = 0
    while i < len(toks):
        t = toks[i]
        nested = None
        if t in ("-f", "-F") and i + 1 < len(toks):
            nested, flag = toks[i + 1], t
            i += 1
        elif t.startswith(("-f", "-F")) and len(t) > 2 and not t.startswith("-fno"):
            nested, flag = t[2:], t[:2]
        if nested:
            out += filelist_fingerprints(os.path.join(ctx, nested) if not os.path.isabs(nested) else nested, root, flag == "-F", seen)
        i += 1
    return out


def engine_identity(exe: str) -> str:
    """`verilator --version` output + realpath: the usual /usr/bin/verilator is a Perl wrapper whose size and mtime
    never change when the engine binary behind it does."""
    real = os.path.realpath(exe)
    if real not in _engine_cache:
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
            ver = (r.stdout or r.stderr or "").strip().splitlines()[0] if (r.stdout or r.stderr) else "?"
        except (OSError, subprocess.SubprocessError):
            ver = "?"
        _engine_cache[real] = f"{ver} @ {real}"
    return _engine_cache[real]


def parse_warnings(stderr: str, cap: int = 500) -> list[dict]:
    out: list[dict] = []
    for line in (stderr or "").splitlines():
        m = _WARN_RE.match(line.strip())
        if not m:
            continue
        out.append({"tag": m.group(1), "file": m.group(2), "line": int(m.group(3)) if m.group(3) else None,
                    "col": int(m.group(4)) if m.group(4) else None, "message": m.group(5).strip()})
        if len(out) >= cap:
            break
    return out


def parse_const(text: Optional[str]):
    """Verilator constant spelling ('32'sh10', "2'h3", '7') -> int, or the text when not numeric."""
    if text is None:
        return None
    m = _CONST_RE.match(text.strip())
    if not m:
        return text
    base = {"b": 2, "o": 8, "d": 10, "h": 16, None: 10}[m.group(2)]
    digits = m.group(3).replace("_", "")
    try:
        return int(digits, base)
    except ValueError:
        return text  # x/z bits


def find_sources(root: str, patterns: list[str], filelist: Optional[str]) -> tuple[list[str], Optional[str]]:
    """Resolve the source list: explicit globs, a -f filelist, a lone *.f at the root, or every *.sv/*.v under root."""
    if filelist:
        if not os.path.isabs(filelist) and os.path.exists(os.path.join(root, filelist)):
            return [], os.path.abspath(os.path.join(root, filelist))     # tracked entries store root-relative lists
        return [], os.path.abspath(filelist)
    files: list[str] = []
    for pat in patterns:
        hits = sorted(glob.glob(os.path.join(root, pat), recursive=True)) if not os.path.isabs(pat) else sorted(glob.glob(pat, recursive=True))
        files += hits
    if files:
        return [os.path.abspath(f) for f in files], None
    fl = sorted(glob.glob(os.path.join(root, "*.f")))
    if fl:
        return [], fl[0]
    for ext in ("sv", "v"):
        files += sorted(glob.glob(os.path.join(root, "**", f"*.{ext}"), recursive=True))
    files = [f for f in files if "/.hx/" not in f and "/obj_dir/" not in f]
    if not files:
        raise FrontendError(f"no SystemVerilog sources found under {root}; pass --sv-file GLOB or -f FILELIST")
    return [os.path.abspath(f) for f in files], None


def resolve_verilator(verilator: str = "verilator") -> str:
    exe = shutil.which(verilator)
    if not exe:
        raise FrontendError(f"verilator executable {verilator!r} not found (needed for SystemVerilog); install it or pass --verilator PATH")
    return exe


def run_verilator(root: str, files: list[str], filelist: Optional[str], top: Optional[str], extra_args: list[str],
                  verilator: str = "verilator") -> tuple[str, list[str], list[dict]]:
    """Returns (xml, command, warnings). Warnings survive -Wno-lint/-Wno-style only when Verilator classes them
    outside those groups (SELRANGE, UNOPTFLAT, …); they are kept apart from errors."""
    exe = resolve_verilator(verilator)
    tmp = tempfile.mkdtemp(prefix="hx-verilator-")
    out = os.path.join(tmp, "design.xml")
    cmd = [exe, "--xml-only", "--xml-output", out, "-Wno-fatal", "-Wno-lint", "-Wno-style", "-Wno-MULTITOP",
           "--Mdir", os.path.join(tmp, "obj")]
    if top:
        cmd += ["--top-module", top]
    if filelist:
        cmd += ["-f", filelist]
    cmd += extra_args
    cmd += files
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        errs = [l for l in (r.stderr or "").splitlines() if "%Error" in l] or (r.stderr or "").splitlines()[-8:]
        raise FrontendError("verilator failed:\n  " + "\n  ".join(errs[:12]))
    with open(out, encoding="utf-8", errors="replace") as fh:
        xml = fh.read()
    shutil.rmtree(tmp, ignore_errors=True)
    return xml, cmd, parse_warnings(r.stderr or "")


# ============================================================ XML -> summary (JSON-able, cacheable)

class _XmlIndexer:
    def __init__(self, xml: str, root: str):
        self.root = root
        self.tree = ET.fromstring(xml)
        self.files: dict[str, str] = {}
        files_el = self.tree.find("files")
        for f in (files_el if files_el is not None else []):
            self.files[f.get("id")] = f.get("filename")
        self.dtypes: dict[str, ET.Element] = {}
        self.src_cache: dict[str, list[str]] = {}
        self.modules: dict[str, dict] = {}      # xml module name -> {origName, file, loc, ports, params, signals, instances, routines, calls}
        self.packages: dict[str, dict] = {}
        self.routines: dict[str, dict] = {}     # key "<scope>::<name>" -> routine summary
        self.types: dict[str, dict] = {}        # type key -> summary
        self.cells: list[dict] = []
        self._spell_cache: dict[str, str] = {}
        self._width_cache: dict[str, Optional[int]] = {}
        self.named: dict[str, str] = {}         # 'pkg::name' and 'name' -> dtype id of struct/union/enum

    # ---------------------------------------------------------------- helpers
    def loc(self, el: ET.Element) -> Optional[dict]:
        l = el.get("loc") or el.get("fl")
        if not l:
            return None
        parts = l.split(",")
        if len(parts) < 2:
            return None
        fname = self.files.get(parts[0], parts[0])
        if fname.startswith("<"):
            return None
        path = fname if os.path.isabs(fname) else os.path.join(self.root, fname)
        d = {"file": os.path.abspath(path), "line": int(parts[1]), "col": int(parts[2]) if len(parts) > 2 else None}
        if len(parts) > 3:
            d["end_line"] = int(parts[3])
            d["end_col"] = int(parts[4]) if len(parts) > 4 else None
        return d

    def src_lines(self, path: str) -> list[str]:
        if path not in self.src_cache:
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    self.src_cache[path] = fh.read().splitlines()
            except OSError:
                self.src_cache[path] = []
        return self.src_cache[path]

    def source_slice(self, loc: Optional[dict], end_kw: tuple[str, ...] = ()) -> tuple[Optional[str], Optional[int]]:
        """(source text, last line) from loc's line to the line holding one of `end_kw` (endmodule, endfunction,
        endtask). Verilator's `loc` end is the NAME token's end, not the construct's, so the end is always scanned."""
        if not loc or not loc.get("file"):
            return None, None
        lines = self.src_lines(loc["file"])
        if not lines or loc["line"] > len(lines):
            return None, None
        start = loc["line"] - 1
        end = None
        for i in range(start, len(lines)):
            if any(re.search(r"\b" + kw + r"\b", lines[i]) for kw in end_kw):
                end = i + 1
                break
        if end is None:
            return None, None
        return "\n".join(lines[start:end]), end

    @staticmethod
    def xml_without_locations(el: ET.Element) -> str:
        """Fallback fingerprint: the elaborated XML subtree with every source position stripped."""
        import copy
        c = copy.deepcopy(el)
        for e in c.iter():
            for a in ("loc", "fl"):
                e.attrib.pop(a, None)
        return ET.tostring(c, encoding="unicode")

    def content_hash(self, el: ET.Element, loc: Optional[dict], end_kw: tuple[str, ...]) -> str:
        text, end = self.source_slice(loc, end_kw)
        if loc is not None and end is not None:
            loc["end_line"] = end          # the construct's real extent (review finding H7)
        return _ids.body_hash(text if text is not None else self.xml_without_locations(el), "sv")

    def text_at(self, loc: Optional[dict], n: int = 2) -> str:
        if not loc:
            return ""
        lines = self.src_lines(loc["file"])
        if not lines or loc["line"] > len(lines):
            return ""
        return lines[loc["line"] - 1][max(0, (loc.get("col") or 1) - 1):][:n]

    def expr_text(self, el: Optional[ET.Element]) -> str:
        """Readable rendering of an elaborated expression (used when the source text is not available)."""
        if el is None:
            return "?"
        tag = el.tag
        kids = list(el)
        if tag in ("varref", "varxref"):
            return (el.get("dotted") + "." if el.get("dotted") else "") + (el.get("name") or "?")
        if tag == "const":
            return str(_values.fmt(_values.encode(el.get("name"))))
        if tag in ("sel", "arraysel", "selbit", "selextract", "selplus", "selminus"):
            base = self.expr_text(kids[0]) if kids else "?"
            idx = ":".join(self.expr_text(k) for k in kids[1:]) if len(kids) > 1 else ""
            return f"{base}[{idx}]" if idx else base
        if tag == "concat":
            return "{" + ", ".join(self.expr_text(k) for k in kids) + "}"
        if tag == "replicate":
            return "{" + " ".join(self.expr_text(k) for k in kids) + "}"
        if tag == "cond":
            return " ? ".join(self.expr_text(k) for k in kids[:1]) + " ? " + " : ".join(self.expr_text(k) for k in kids[1:])
        if tag == "membersel":
            return (self.expr_text(kids[0]) if kids else "?") + "." + (el.get("name") or "?")
        if len(kids) == 1:
            return f"{tag}({self.expr_text(kids[0])})"
        if len(kids) == 2:
            return f"({self.expr_text(kids[0])} {tag} {self.expr_text(kids[1])})"
        return tag

    def port_text(self, p: ET.Element) -> str:
        """`.name(expression)` as written: parenthesised source text; shorthand `.clk_i`; `.*`; else the XML expression."""
        name = p.get("name")
        ploc = self.loc(p)
        txt = self.paren_text(ploc)
        if txt is not None:
            return f".{name}({txt})"
        kids = list(p)
        src = self.text_at(ploc, 2)
        if src == ".*":
            return f".{name}(.*)"
        if kids and kids[0].tag == "varref" and self.loc(kids[0]) == ploc:
            return f".{name}({kids[0].get('name')})"              # shorthand `.clk_i`
        return f".{name}({self.expr_text(kids[0]) if kids else ''})"

    def paren_text(self, loc: Optional[dict]) -> Optional[str]:
        """Text inside the parentheses that follow a token located at loc (call args, port connection)."""
        if not loc:
            return None
        lines = self.src_lines(loc["file"])
        if not lines or loc["line"] > len(lines):
            return None
        li, ci = loc["line"] - 1, (loc.get("end_col") or loc.get("col") or 1) - 1
        buf, depth, started = [], 0, False
        while li < len(lines) and li < loc["line"] + 40:
            line = lines[li]
            while ci < len(line):
                ch = line[ci]
                if not started:
                    if ch == "(":
                        started, depth = True, 1
                    elif ch not in " \t":
                        return None
                else:
                    if ch in "([{":
                        depth += 1
                    elif ch in ")]}":
                        depth -= 1
                        if depth == 0:
                            return re.sub(r"\s+", " ", "".join(buf)).strip()
                    buf.append(ch)
                ci += 1
            buf.append(" ")
            li, ci = li + 1, 0
        return None

    @staticmethod
    def split_args(text: Optional[str]) -> list[str]:
        if not text:
            return []
        out, depth, cur = [], 0, []
        for ch in text:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            if ch == "," and depth == 0:
                out.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        tail = "".join(cur).strip()
        if tail or out:
            out.append(tail)
        return out

    # ---------------------------------------------------------------- types
    def spell(self, dtype_id: Optional[str]) -> str:
        if not dtype_id:
            return "?"
        if dtype_id in self._spell_cache:
            return self._spell_cache[dtype_id]
        el = self.dtypes.get(dtype_id)
        if el is None:
            return "?"
        tag = el.tag
        self._spell_cache[dtype_id] = "…"  # cycle guard
        if tag == "basicdtype":
            s = el.get("name") or "logic"
            if el.get("left") is not None:
                s += f" [{el.get('left')}:{el.get('right')}]"
            if el.get("signed") == "true" and el.get("name") not in ("int", "integer", "byte", "shortint", "longint"):
                s += " signed"
        elif tag in ("structdtype", "uniondtype", "enumdtype", "classrefdtype"):
            s = el.get("name") if el.get("name") and not _is_implicit_name(el.get("name")) else f"(anonymous {tag[:-5]})"
        elif tag == "refdtype":
            s = el.get("name") or self.spell(el.get("sub_dtype_id"))
        elif tag in ("packarraydtype", "unpackarraydtype"):
            sub = self.spell(el.get("sub_dtype_id"))
            rng = el.find("range")
            consts = [c.get("name") for c in rng.findall("const")] if rng is not None else []
            vals = [parse_const(c) for c in consts]
            if tag == "packarraydtype":
                dim = f"[{vals[0]}:{vals[1]}]" if len(vals) == 2 else "[]"
                head, _, rest = sub.partition(" ")
                s = f"{head} {dim}{rest}" if rest else f"{head} {dim}"
            else:
                dim = f"[{vals[0]}:{vals[1]}]" if len(vals) == 2 and vals[1] != 0 else (f"[{vals[0] + 1}]" if len(vals) == 2 and isinstance(vals[0], int) else "[]")
                s = f"{sub} {dim}"
        elif tag == "voiddtype":
            s = "void"
        else:
            s = el.get("name") or tag.replace("dtype", "")
        self._spell_cache[dtype_id] = s
        return s

    def width(self, dtype_id: Optional[str]) -> Optional[int]:
        """Bit width, or None for unpacked/unknown."""
        if not dtype_id:
            return None
        if dtype_id in self._width_cache:
            return self._width_cache[dtype_id]
        el = self.dtypes.get(dtype_id)
        self._width_cache[dtype_id] = None
        w: Optional[int] = None
        if el is not None:
            tag = el.tag
            if tag == "basicdtype":
                if el.get("left") is not None:
                    try:
                        w = abs(int(el.get("left")) - int(el.get("right"))) + 1
                    except (TypeError, ValueError):
                        w = None
                else:
                    w = {"int": 32, "integer": 32, "byte": 8, "shortint": 16, "longint": 64, "time": 64, "real": 64,
                         "shortreal": 32}.get(el.get("name"), 1)
            elif tag in ("refdtype", "enumdtype"):
                w = self.width(el.get("sub_dtype_id"))
            elif tag == "structdtype":
                ws = [self.width(m.get("sub_dtype_id")) for m in el.findall("memberdtype")]
                w = sum(ws) if ws and all(x is not None for x in ws) else None
            elif tag == "uniondtype":
                ws = [self.width(m.get("sub_dtype_id")) for m in el.findall("memberdtype")]
                w = max(ws) if ws and all(x is not None for x in ws) else None
            elif tag == "packarraydtype":
                sub = self.width(el.get("sub_dtype_id"))
                rng = el.find("range")
                vals = [parse_const(c.get("name")) for c in rng.findall("const")] if rng is not None else []
                if sub is not None and len(vals) == 2 and all(isinstance(v, int) for v in vals):
                    w = sub * (abs(vals[0] - vals[1]) + 1)
        self._width_cache[dtype_id] = w
        return w

    def type_key(self, dtype_id: Optional[str]) -> Optional[str]:
        """Record a named type (struct/union/enum/alias) and return its key; None for basic/array types."""
        if not dtype_id:
            return None
        el = self.dtypes.get(dtype_id)
        if el is None:
            return None
        tag = el.tag
        if tag in ("packarraydtype", "unpackarraydtype"):
            return self.type_key(el.get("sub_dtype_id"))
        if tag not in ("structdtype", "uniondtype", "enumdtype", "refdtype"):
            return None
        name = el.get("name") or ""
        if _is_implicit_name(name):
            name = ""                      # Verilator's `scope.__typeimpsu4` for an inline struct: a counter, not a name
        if tag == "refdtype":
            key = f"alias:{name}:{el.get('sub_dtype_id')}"
        else:
            key = f"{tag}:{dtype_id}"
        if key in self.types:
            return key
        loc = self.loc(el)
        # Verilator names module-scoped types `module.name` and package-scoped ones `pkg::name`
        scope_kind = "package" if "::" in name else ("module" if "." in name else ("anonymous" if not name else "unit"))
        entry = {"kind": {"structdtype": "struct", "uniondtype": "union", "enumdtype": "enum", "refdtype": "typedef"}[tag],
                 "name": name.split("::")[-1], "qualname": name, "loc": loc, "size": self.width(dtype_id),
                 "fields": [], "enumerators": [], "underlying": None, "underlying_key": None, "field_keys": [],
                 "anonymous": not name, "system": False, "scope_kind": scope_kind, "ctx": None}
        self.types[key] = entry
        if tag in ("structdtype", "uniondtype"):
            members = el.findall("memberdtype")
            widths = [self.width(m.get("sub_dtype_id")) for m in members]
            packed = bool(widths) and all(w is not None for w in widths)
            total = sum(widths) if packed else None
            running = total
            for m, w in zip(members, widths):
                sub = m.get("sub_dtype_id")
                fk = self.type_key(sub)
                lsb = None
                if packed and tag == "structdtype":
                    running -= w
                    lsb = running
                elif packed:
                    lsb = 0
                entry["fields"].append({"name": m.get("name"), "type": self.spell(sub), "type_key": fk,
                                        "bit_offset": lsb, "bit_width": w})
                if fk:
                    entry["field_keys"].append(fk)
            entry["packed"] = packed
        elif tag == "enumdtype":
            entry["underlying"] = self.spell(el.get("sub_dtype_id"))
            for item in el.findall("enumitem"):
                c = item.find("const")
                entry["enumerators"].append({"name": item.get("name"), "value": _values.encode(c.get("name")) if c is not None else None})
        else:  # typedef alias
            entry["underlying"] = self.spell(el.get("sub_dtype_id"))
            entry["underlying_key"] = self.type_key(el.get("sub_dtype_id"))
            entry["size"] = self.width(el.get("sub_dtype_id"))
            if entry["underlying_key"] and loc is None:
                entry["loc"] = self.types[entry["underlying_key"]].get("loc")
        return key

    # ---------------------------------------------------------------- modules / routines
    def named_key(self, name: Optional[str], local: Optional[dict] = None) -> Optional[str]:
        """Type key for a declared type name ('state_t', 'dma_pkg::cfg_t'). `local` is the specialization's own
        name -> dtype map and wins over the global first-match map, so a lowered `fp_t` inside the 64-bit
        specialization resolves to the 64-bit layout (review finding H3)."""
        if not name:
            return None
        did = (local or {}).get(name) or (local or {}).get(name.split("::")[-1])
        if did is None:
            did = self.named.get(name)
        if did is None and "::" not in name:
            cands = [k for k in self.named if k.endswith("::" + name)]
            did = self.named[cands[0]] if len(cands) == 1 else None
        return self.type_key(did) if did else None

    def local_named(self, m: ET.Element) -> dict:
        """Type names declared or used inside one module specialization -> dtype id."""
        out: dict[str, str] = {}
        for td in m.findall("typedef"):
            if td.get("name") and td.get("dtype_id"):
                out.setdefault(td.get("name"), td.get("dtype_id"))
        for v in m.iter("var"):
            el = self.dtypes.get(v.get("dtype_id") or "")
            if el is not None and el.tag in ("structdtype", "uniondtype", "enumdtype") and el.get("name") and not _is_implicit_name(el.get("name")):
                out.setdefault(el.get("name"), el.get("id"))
                out.setdefault(el.get("name").split("::")[-1].split(".")[-1], el.get("id"))
        return out

    def var_info(self, v: ET.Element, scope: Optional[str] = None, local: Optional[dict] = None) -> dict:
        dtype_id = v.get("dtype_id")
        tkey = self.type_key(dtype_id)
        spelled = self.spell(dtype_id)
        vartype = v.get("vartype")
        if tkey is None and vartype and vartype not in ("logic", "port", "int", "integer", "bit", "wire", "reg", "byte", "real", "time", "string"):
            nk = self.named_key(vartype, local)    # enum/struct typedef lowered by verilator: recover from the declared name
            if nk:
                tkey = nk
                spelled = self.idx_name(nk) or vartype
        name = v.get("origName") or v.get("name")
        t = self.types.get(tkey) if tkey else None
        if t is not None and t["anonymous"] and not t.get("ctx") and scope:
            t["ctx"] = f"{scope}.{name}"           # anonymous types are named by their first declaring context (H6)
        d = {"name": name, "dtype_id": dtype_id, "type": spelled,
             "type_key": tkey, "dir": DIR_MAP.get(v.get("dir") or "", None), "loc": self.loc(v),
             "width": self.width(dtype_id)}
        c = v.find("const")
        if c is not None:
            d["value"] = _values.encode(c.get("name"))   # JSON-safe: wide values are canonical strings (H1)
        return d

    def name_nested_anonymous(self) -> None:
        """Anonymous types only reachable as fields: `<parent ctx or name>.<field>`; the rest fall back to `anon#<hash>` in _link."""
        for _ in range(8):
            changed = False
            for t in self.types.values():
                parent = t.get("ctx") or (t.get("qualname") if not t["anonymous"] else None)
                if not parent:
                    continue
                for f in t.get("fields", []):
                    ft = self.types.get(f.get("type_key") or "")
                    if ft is not None and ft["anonymous"] and not ft.get("ctx"):
                        ft["ctx"] = f"{parent}.{f['name']}"
                        changed = True
            if not changed:
                break

    def idx_name(self, key: str) -> Optional[str]:
        t = self.types.get(key)
        return (t.get("qualname") or t.get("name")) if t else None

    def typedef(self, el: ET.Element, scope: str, scope_kind: str = "package") -> Optional[str]:
        """Module/package `typedef name` -> alias entry (also binds the bare name to its struct/enum)."""
        name, did = el.get("name"), el.get("dtype_id")
        if not name or not did:
            return None
        target = self.type_key(did) or self.named_key(name)
        key = f"alias:{scope}::{name}"
        if key in self.types:
            return key
        loc = self.loc(el)
        base = self.types.get(target) if target else None
        sep = "::" if scope_kind == "package" else "."
        self.types[key] = {"kind": "typedef", "name": name, "qualname": f"{scope}{sep}{name}" if scope not in ("$unit", "") else name,
                           "loc": loc or (base or {}).get("loc"), "size": (base or {}).get("size") if base else self.width(did),
                           "fields": [], "enumerators": [], "underlying": self.idx_name(target) if target else self.spell(did),
                           "underlying_key": target, "field_keys": [], "anonymous": False, "system": False,
                           "scope_kind": scope_kind, "ctx": None}
        if base is not None and base["anonymous"] and not base.get("ctx"):
            base["ctx"] = f"{scope}{sep}{name}"          # `typedef struct {…} name` inside a module
        return key

    def routine(self, scope: str, scope_file: Optional[str], el: ET.Element, local: Optional[dict] = None) -> str:
        """Record a func/task; returns its key '<scope>::<name>'."""
        name = el.get("name")
        key = f"{scope}::{name}"
        if key in self.routines:
            return key
        loc = self.loc(el)
        params, ret, type_keys = [], None, []
        for v in el.findall("var"):
            info = self.var_info(v, f"{scope}.{name}", local)
            if not info["dir"]:
                continue  # local
            if el.tag == "func" and v.get("name") == name and v.get("dir") == "output":
                ret = info
                continue
            params.append(info)
            if info["type_key"]:
                type_keys.append(info["type_key"])
        if ret and ret["type_key"]:
            type_keys.append(ret["type_key"])
        ptxt = ", ".join(f"{ {'in': 'input', 'out': 'output', 'inout': 'inout'}[p['dir']] } {p['type']} {p['name']}" for p in params)
        kw = "function" if el.tag == "func" else "task"
        sig = f"{kw} {ret['type'] + ' ' if ret else ''}{scope}::{name}({ptxt})"
        calls = self.collect_calls(el)
        self.routines[key] = {"key": key, "kind": "function" if el.tag == "func" else "task", "name": name, "scope": scope,
                              "qualname": f"{scope}.{name}", "loc": loc, "file": (loc or {}).get("file") or scope_file,
                              "signature": sig, "params": params, "returns": ret, "calls": calls, "type_keys": type_keys,
                              "body_hash": self.content_hash(el, loc, ("endfunction", "endtask"))}
        return key

    def collect_calls(self, el: ET.Element, skip_nested_routines: bool = False) -> list[dict]:
        out = []
        for child in el:
            if skip_nested_routines and child.tag in ("func", "task"):
                continue
            if child.tag in ("funcref", "taskref"):
                loc = self.loc(child)
                out.append({"name": child.get("name"), "kind": "call", "loc": loc, "args": self.split_args(self.paren_text(loc))})
            out += self.collect_calls(child, skip_nested_routines)
        return out

    def index(self) -> dict:
        nl = self.tree.find("netlist")
        if nl is None:
            raise FrontendError("verilator XML has no <netlist>")
        tt = nl.find("typetable")
        if tt is not None:
            for d in tt:
                if d.get("id"):
                    self.dtypes[d.get("id")] = d
                    if d.tag in ("structdtype", "uniondtype", "enumdtype") and d.get("name") and not _is_implicit_name(d.get("name")):
                        self.named.setdefault(d.get("name"), d.get("id"))
                        self.named.setdefault(d.get("name").split("::")[-1], d.get("id"))
        for pk in nl.findall("package"):
            pname = pk.get("origName") or pk.get("name")
            if pname.startswith("__024unit") or pname == "$unit":
                pname = "$unit"
            ploc = self.loc(pk)
            entry = {"name": pname, "loc": ploc, "routines": [], "typedefs": []}
            for td in pk.findall("typedef"):
                k = self.typedef(td, pname, "package")
                if k:
                    entry["typedefs"].append(k)
            for r in list(pk.findall("func")) + list(pk.findall("task")):
                entry["routines"].append(self.routine(pname, (ploc or {}).get("file"), r))
            self.packages[pname] = entry
        for m in nl.findall("module"):
            xname = m.get("name")
            oname = m.get("origName") or xname
            mloc = self.loc(m)
            local = self.local_named(m)
            ports, params, signals, type_keys = [], [], [], []
            for v in m.findall("var"):
                info = self.var_info(v, oname, local)
                if v.get("param") == "true":
                    params.append(info)
                elif info["dir"]:
                    ports.append(info)
                    if info["type_key"]:
                        type_keys.append(info["type_key"])
                else:
                    signals.append({"name": info["name"], "type": info["type"], "type_key": info["type_key"]})
                    if info["type_key"]:
                        type_keys.append(info["type_key"])
            for td in m.findall("typedef"):
                self.typedef(td, oname, "module")
            routines = [self.routine(oname, (mloc or {}).get("file"), r, local) for r in list(m.findall("func")) + list(m.findall("task"))]
            instances: list[dict] = []
            self._collect_instances(m, "", instances)        # direct children AND generate scopes (review finding H4)
            calls = self.collect_calls(m, skip_nested_routines=True)
            self.modules[xname] = {"xname": xname, "name": oname, "loc": mloc, "file": (mloc or {}).get("file"),
                                   "ports": ports, "params": params, "signals": signals, "routines": routines,
                                   "instances": instances, "calls": calls, "type_keys": _uniq(type_keys),
                                   "top": m.get("topModule") == "1",
                                   # the module's SOURCE, module…endmodule: procedural logic and assigns count,
                                   # comments and line positions do not (review finding H2)
                                   "body_hash": self.content_hash(m, mloc, ("endmodule",))}
        self.name_nested_anonymous()
        cells = self.tree.find("cells")
        if cells is not None:
            for c in cells:
                self._walk_cells(c, None)
        deps = sorted({os.path.abspath(f if os.path.isabs(f) else os.path.join(self.root, f))
                       for f in self.files.values() if not f.startswith("<")})
        return {"files": self.files, "modules": self.modules, "packages": self.packages, "routines": self.routines,
                "types": self.types, "cells": self.cells, "deps": TUCache.snapshot_deps(deps)}

    def _collect_instances(self, el: ET.Element, scope: str, out: list[dict]) -> None:
        """Instances directly under a module and inside nested generate scopes (`<begin name="gen_x[0]">`), each
        keyed by its scope path so cells such as `top.gen_x[0].u_y` can be matched."""
        for child in el:
            if child.tag == "instance":
                name = child.get("origName") or child.get("name")
                out.append({"name": name, "path": f"{scope}.{name}" if scope else name, "defName": child.get("defName"),
                            "loc": self.loc(child), "connections": [self.port_text(p) for p in child.findall("port")]})
            elif child.tag == "begin":
                bname = decode_verilator_name(child.get("name") or "")
                self._collect_instances(child, f"{scope}.{bname}" if scope and bname else (bname or scope), out)
            elif child.tag in ("if", "case", "while", "for", "always", "initial", "generate"):
                self._collect_instances(child, scope, out)

    def _walk_cells(self, c: ET.Element, parent: Optional[str]) -> None:
        raw = c.get("hier")
        hier = decode_verilator_name(raw)                   # source spelling: gen_x[0].u_y, not __BRA__0__KET__ (H10)
        self.cells.append({"hier": hier, "raw_hier": raw, "name": decode_verilator_name(c.get("name") or ""),
                           "submodname": c.get("submodname"), "parent": parent, "loc": self.loc(c)})
        for k in c.findall("cell"):
            self._walk_cells(k, hier)


def _uniq(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# ============================================================ Frontend

class VerilatorFrontend(Frontend):
    lang = "sv"

    def __init__(self, root: str, *, sv_files: list[str] | None = None, filelist: Optional[str] = None,
                 top: Optional[str] = None, extra_args: list[str] | None = None, cache_dir: Optional[str] = None,
                 use_cache: bool = True, verilator: str = "verilator", verbose: bool = False):
        self.root = os.path.abspath(root)
        self.sv_files = list(sv_files or [])
        self.filelist = filelist
        self.top = top
        self.extra_args = list(extra_args or [])
        self.verilator = verilator
        self.verbose = verbose
        self.cache = TUCache(cache_dir or os.path.join(self.root, ".hx", "cache"), enabled=use_cache)
        self.stats: dict = {}
        self.notes: list[str] = []
        self.errors: list[dict] = []
        self.diagnostics: list[dict] = []
        self.idx: dict = {}
        self.cell_by_hier: dict[str, dict] = {}
        self.children: dict[str, list[dict]] = {}
        self.module_by_name: dict[str, dict] = {}
        self.ids: dict[str, str] = {}
        self.type_ids: dict[str, str] = {}
        self.routine_callers: dict[str, list[tuple[str, dict]]] = {}
        self._argument_deps: dict[str, Optional[int]] = {}

    def provenance_inputs(self) -> dict[str, Optional[int]]:
        return {**self._argument_deps, **self.idx.get("deps", {})}

    def cache_identity(self, files: list[str], filelist: Optional[str]) -> tuple[list[str], tuple]:
        """(key args, extra): everything that shapes the elaboration. The executable is resolved FIRST (a missing
        engine must fail even with a warm cache); argument files are fingerprinted by their expanded content with
        Verilator's own nesting rules; the engine is identified by `--version`, not the wrapper's mtime (H2)."""
        exe = resolve_verilator(self.verilator)
        key_args = ["-f", filelist] if filelist else list(files)
        key_args = key_args + (["--top-module", self.top] if self.top else []) + self.extra_args
        fps: list[tuple[str, str]] = []
        if filelist:
            fps += filelist_fingerprints(filelist, self.root, via_F=False)
        args = self.extra_args
        for i, a in enumerate(args):
            if a in ("-f", "-F") and i + 1 < len(args):
                fps += filelist_fingerprints(os.path.join(self.root, args[i + 1]), self.root, via_F=(a == "-F"))
        extra = (SUMMARY_VERSION, self.root, engine_identity(exe), tuple(fps), self.top or "", tuple(self.extra_args))
        return key_args, extra

    def build_index(self) -> None:
        t0 = time.time()
        files, filelist = find_sources(self.root, self.sv_files, self.filelist)
        key_args, extra = self.cache_identity(files, filelist)
        self._argument_deps = TUCache.snapshot_deps([path for path, _ in extra[3]])
        cached = self.cache.load("<verilator>", key_args, extra)
        if cached is not None:
            self.idx = cached
            self.stats["cached"] = 1
        else:
            xml, cmd, warnings = run_verilator(self.root, files, filelist, self.top, self.extra_args, self.verilator)
            self.idx = _XmlIndexer(xml, self.root).index()
            self.idx["command"] = cmd
            self.idx["warnings"] = warnings
            self.cache.store("<verilator>", key_args, self.idx, extra)
            self.stats["cached"] = 0
        self._link()
        warnings = self.idx.get("warnings") or []
        by_tag: dict[str, int] = {}
        for w in warnings:
            by_tag[w["tag"]] = by_tag.get(w["tag"], 0) + 1
        self.stats.update({"tus": 1, "parsed": 1 - self.stats["cached"], "tu_errors": 0, "diagnostics": 0,
                           "warnings": len(warnings), "warnings_by_tag": dict(sorted(by_tag.items(), key=lambda kv: -kv[1])),
                           "index_seconds": round(time.time() - t0, 2), "modules_indexed": len(self.idx["modules"]),
                           "cells": len(self.idx["cells"]), "types_indexed": len(self.idx["types"])})
        if warnings:
            tags = ", ".join(f"{t} {n}" for t, n in list(self.stats["warnings_by_tag"].items())[:4])
            self.notes.append(f"verilator: {len(warnings)} warning(s) ({tags}); see meta.index.warnings_by_tag"
                              + (" and --verbose for the first ones" if not self.verbose else ""))
            if self.verbose:
                for w in warnings[:20]:
                    where = f"{w['file']}:{w['line']}: " if w.get("file") else ""
                    print(f"verilator   %Warning-{w['tag']}: {where}{w['message']}")

    # ---------------------------------------------------------------- linking: keys -> stable ids
    def _rel(self, path: Optional[str]) -> str:
        return _ids.rel(path, self.root) if path else "?"

    def type_fingerprint(self, key: str, _stack: Optional[tuple] = None) -> str:
        """8-hex fingerprint of a type's LAYOUT: kind, size, packed flag, fields (name, spelled type incl. signedness,
        width, offset, nested fingerprint), enumerators (name=value), underlying. Never XML dtype ids or declaration
        order, so it is the same across runs and specializations with identical layouts (H3)."""
        cache = self.__dict__.setdefault("_fp_cache", {})
        if key in cache:
            return cache[key]
        stack = _stack or ()
        if key in stack:
            return "cycle"
        t = self.idx["types"].get(key)
        if t is None:
            return "none"
        data: list = [t["kind"], t.get("size"), bool(t.get("packed"))]
        for f in t.get("fields", []):
            data.append((f["name"], f["type"], f.get("bit_width"), f.get("bit_offset"),
                         self.type_fingerprint(f["type_key"], stack + (key,)) if f.get("type_key") else None))
        for e in t.get("enumerators", []):
            data.append((e["name"], str(e.get("value"))))
        data.append(t.get("underlying"))
        if t.get("underlying_key"):
            data.append(self.type_fingerprint(t["underlying_key"], stack + (key,)))
        fp = _ids.short_hash(repr(data), 8)
        cache[key] = fp
        return fp

    def _type_name(self, key: str, t: dict) -> str:
        """Id rule (hx/2): package-scoped types keep their name; a type declared inside a module is identified by its
        layout (`module.name@<fp>`), anonymous types by their first declaring context plus layout."""
        if t["anonymous"]:
            base = t.get("ctx") or f"anon#{self.type_fingerprint(key)}"
            return f"{base}@{self.type_fingerprint(key)}"
        q = t.get("qualname") or t["name"]
        if t.get("scope_kind") == "module" or (t.get("scope_kind") is None and "." in q and "::" not in q):
            return f"{q}@{self.type_fingerprint(key)}"
        return q

    def _link(self) -> None:
        idx = self.idx
        self.module_by_name = {m["xname"]: m for m in idx["modules"].values()}
        for m in self.module_by_name.values():
            m["inst_by_path"] = {i.get("path") or i["name"]: i for i in m["instances"]}
        for c in idx["cells"]:
            self.cell_by_hier[c["hier"]] = c
            if c["parent"]:
                self.children.setdefault(c["parent"], []).append(c)
        for c in idx["cells"]:
            m = self.module_by_name.get(c["submodname"])
            self.ids["cell:" + c["hier"]] = _ids.node_id("sv", self._rel(m["file"] if m else None), c["hier"])
        for key, r in idx["routines"].items():
            self.ids["routine:" + key] = _ids.node_id("sv", self._rel(r["file"]), r["qualname"])
        for key, t in idx["types"].items():
            self.type_ids[key] = _ids.type_id("sv", self._rel((t.get("loc") or {}).get("file")), t["kind"], self._type_name(key, t))
        # routine callers: instances whose module calls it, and routines that call it
        for c in idx["cells"]:
            m = self.module_by_name.get(c["submodname"])
            if not m:
                continue
            for cs in m["calls"]:
                rk = self._resolve_routine(cs["name"], m["name"])
                if rk:
                    self.routine_callers.setdefault(rk, []).append(("cell:" + c["hier"], cs))
        for key, r in idx["routines"].items():
            for cs in r["calls"]:
                rk = self._resolve_routine(cs["name"], r["scope"])
                if rk:
                    self.routine_callers.setdefault(rk, []).append(("routine:" + key, cs))

    def _resolve_routine(self, name: str, scope: str) -> Optional[str]:
        if "::" in name:
            return name if name in self.idx["routines"] else None
        if f"{scope}::{name}" in self.idx["routines"]:
            return f"{scope}::{name}"
        hits = [k for k in self.idx["routines"] if k.endswith("::" + name)]
        return hits[0] if hits else None

    # ---------------------------------------------------------------- Frontend API
    def _mkloc(self, d: Optional[dict]) -> Optional[Loc]:
        if not d:
            return None
        return Loc(file=self._rel(d["file"]), line=d["line"], end_line=d.get("end_line"), col=d.get("col"))

    def _design_files(self) -> set[str]:
        return {os.path.abspath(f if os.path.isabs(f) else os.path.join(self.root, f)) for f in self.idx["files"].values()
                if not f.startswith("<")}

    def _module_file(self, submodname: str) -> Optional[str]:
        m = self.module_by_name.get(submodname)
        return os.path.abspath(m["file"]) if m and m.get("file") else None

    def locate_entry(self, file: str, symbol: str) -> str:
        """`file` is part of the contract (H9): a module/function name must be DEFINED in it; an instance path's
        file must define the module of some cell on the path (top, an intermediate, or the leaf). Generate-array
        spellings are accepted in either form (`gen_x[0]` or Verilator's `gen_x__BRA__0__KET__`)."""
        cells = self.idx["cells"]
        symbol = decode_verilator_name(symbol)
        abs_file = os.path.abspath(file if os.path.isabs(file) else os.path.join(self.root, file))
        rel_file = self._rel(abs_file)
        design = self._design_files()
        if symbol in self.cell_by_hier:
            # an instance path: the file must define the module of SOME cell on the path (top, intermediate or leaf)
            ok: set[str] = set()
            segs = symbol.split(".")
            for i in range(1, len(segs) + 1):
                cell = self.cell_by_hier.get(".".join(segs[:i]))
                f = self._module_file(cell["submodname"]) if cell else None
                if f:
                    ok.add(f)
            if abs_file not in ok:
                hint = "" if abs_file in design else f" ({rel_file} is not part of the elaborated design)"
                raise EntryNotFound(f"{rel_file} defines no module on the path '{symbol}'{hint}; use one of: "
                                    + ", ".join(sorted(self._rel(f) for f in ok)), [f"{self._rel(f)}:{symbol}" for f in sorted(ok)])
            return "cell:" + symbol
        by_mod = [c for c in cells if (self.module_by_name.get(c["submodname"]) or {}).get("name") == symbol]
        if len(by_mod) > 1:
            raise EntryNotFound(f"module '{symbol}' is instantiated {len(by_mod)} times; name one instance path",
                                [c["hier"] for c in by_mod][:8])
        if len(by_mod) == 1:
            defined_in = self._module_file(by_mod[0]["submodname"])
            if defined_in and abs_file != defined_in:
                hint = "" if abs_file in design else f" ({rel_file} is not part of the elaborated design)"
                raise EntryNotFound(f"module '{symbol}' is defined in {self._rel(defined_in)}, not in {rel_file}{hint}",
                                    [f"{self._rel(defined_in)}:{symbol}"])
            return "cell:" + by_mod[0]["hier"]
        for key, r in self.idx["routines"].items():
            if symbol in (r["name"], r["qualname"], key):
                if r.get("file") and os.path.abspath(r["file"]) != abs_file:
                    raise EntryNotFound(f"'{symbol}' is defined in {self._rel(r['file'])}, not in {rel_file}", [f"{self._rel(r['file'])}:{symbol}"])
                return "routine:" + key
        import difflib
        names = [c["hier"] for c in cells] + [r["qualname"] for r in self.idx["routines"].values()]
        sugg = difflib.get_close_matches(symbol, names, n=5, cutoff=0.5)
        raise EntryNotFound(f"'{symbol}' is neither a module, an instance path nor a function/task in the elaborated design "
                            f"(top: {[c['hier'] for c in cells if not c['parent']]})", sugg)

    def stable_id(self, key: str) -> Optional[str]:
        return self.ids.get(key)

    @staticmethod
    def _instance_of(m: dict, parent: dict, child: dict) -> Optional[dict]:
        """The parent module's instance record for a child cell: by scope path (`gen_lane[0].u_lane`), else by name."""
        rel = child["hier"][len(parent["hier"]) + 1:] if child["hier"].startswith(parent["hier"] + ".") else child["name"]
        by_path = m.get("inst_by_path") or {}
        inst = by_path.get(rel)
        if inst is None:
            same = [i for i in m["instances"] if i["name"] == child["name"]]
            inst = same[0] if len(same) == 1 else None
        return inst

    def _port_params(self, ports: list[dict]) -> list[Param]:
        return [Param(name=p["name"], type=p["type"], type_ref=self.type_ids.get(p["type_key"] or ""), dir=p["dir"],
                      dir_source="explicit") for p in ports]

    def function(self, key: str) -> Optional[FunctionRecord]:
        if key.startswith("cell:"):
            c = self.cell_by_hier.get(key[5:])
            if not c:
                return None
            m = self.module_by_name.get(c["submodname"])
            if not m:
                return None
            params_txt = ", ".join(f"{p['name']}={_values.fmt(p.get('value'))}" for p in m["params"])   # compact, never 5,000 chars (H1)
            ports_txt = ", ".join(p["name"] for p in m["ports"])
            if c["parent"]:
                sig = f"{m['name']}{' #(' + params_txt + ')' if params_txt else ''} {c['name']} ({ports_txt})"
            else:
                sig = f"module {m['name']}{' #(' + params_txt + ')' if params_txt else ''} ({ports_txt})"
            node = Node(id=self.ids[key], kind="module" if not c["parent"] else "instance", name=c["name"], qualname=c["hier"],
                        lang="sv", loc=self._mkloc(m["loc"]) or Loc(file="?", line=0), signature=sig, storage=None,
                        body_hash=m["body_hash"],
                        precision="exact", returns=None, params=self._port_params(m["ports"]), globals=GlobalRefs(),
                        attrs={"module": m["name"], "specialization": m["xname"] if m["xname"] != m["name"] else None,
                               "parameters": {p["name"]: p.get("value") for p in m["params"]},
                               "signals": [{"name": s["name"], "type": s["type"]} for s in m["signals"]]})
            callsites = []
            for ch in self.children.get(c["hier"], []):
                inst = self._instance_of(m, c, ch)
                callsites.append(CallSite(callee_key="cell:" + ch["hier"], name=ch["name"], loc=self._mkloc(inst["loc"] if inst else None),
                                          kind="instance", args=list(inst["connections"]) if inst else []))
            seen = set()
            for cs in m["calls"]:
                rk = self._resolve_routine(cs["name"], m["name"])
                sig_key = (rk or cs["name"], (cs.get("loc") or {}).get("line"))
                if sig_key in seen:
                    continue
                seen.add(sig_key)
                callsites.append(CallSite(callee_key=("routine:" + rk) if rk else None, name=cs["name"], loc=self._mkloc(cs.get("loc")),
                                          kind="call", args=list(cs.get("args", []))))
            return FunctionRecord(node=node, callsites=callsites, type_keys=list(m["type_keys"]), global_keys=[])
        if key.startswith("routine:"):
            r = self.idx["routines"].get(key[8:])
            if not r:
                return None
            ret = r.get("returns")
            node = Node(id=self.ids[key], kind=r["kind"], name=r["name"], qualname=r["qualname"], lang="sv",
                        loc=self._mkloc(r["loc"]) or Loc(file="?", line=0), signature=r["signature"], storage=None,
                        body_hash=r["body_hash"], precision="exact",
                        returns=TypeUse(type=ret["type"], type_ref=self.type_ids.get(ret["type_key"] or "")) if ret else None,
                        params=self._port_params(r["params"]), globals=GlobalRefs(), attrs={"scope": r["scope"]})
            callsites = []
            for cs in r["calls"]:
                rk = self._resolve_routine(cs["name"], r["scope"])
                callsites.append(CallSite(callee_key=("routine:" + rk) if rk else None, name=cs["name"], loc=self._mkloc(cs.get("loc")),
                                          kind="call", args=list(cs.get("args", []))))
            return FunctionRecord(node=node, callsites=callsites, type_keys=list(r["type_keys"]), global_keys=[])
        return None

    def declaration(self, key: str) -> Optional[DeclRecord]:
        if key.startswith("cell:"):
            c = self.cell_by_hier.get(key[5:])
            if not c:
                return None
            m = self.module_by_name.get(c["submodname"])
            loc = self._mkloc(m["loc"]) if m else None
            return DeclRecord(id=self.ids[key], name=c["name"], loc=loc, has_definition=m is not None, system=False,
                              relpath=loc.file if loc else None)
        if key.startswith("routine:"):
            r = self.idx["routines"].get(key[8:])
            if not r:
                return None
            loc = self._mkloc(r["loc"])
            return DeclRecord(id=self.ids[key], name=r["name"], loc=loc, has_definition=True, system=False, relpath=loc.file if loc else None)
        return None

    def type(self, key: str) -> Optional[TypeRecord]:
        t = self.idx["types"].get(key)
        if t is None:
            return None
        td = TypeDef(id=self.type_ids[key], kind=t["kind"], name=t["qualname"] or t["name"] or f"(anonymous {t['kind']})", lang="sv",
                     loc=self._mkloc(t.get("loc")), size=t.get("size"), align=None,
                     fields=[Field(name=f["name"], type=f["type"], type_ref=self.type_ids.get(f["type_key"] or ""), offset=None,
                                   size=f["bit_width"], bit_offset=f["bit_offset"], bit_width=f["bit_width"]) for f in t.get("fields", [])],
                     enumerators=[Enumerator(name=e["name"], value=e["value"]) for e in t.get("enumerators", [])],
                     underlying=t.get("underlying"), underlying_ref=self.type_ids.get(t.get("underlying_key") or ""),
                     anonymous=t["anonymous"], system=False)
        return TypeRecord(typedef=td, nested_keys=list(t.get("field_keys", [])), alias_keys=[t["underlying_key"]] if t.get("underlying_key") else [])

    def global_var(self, key: str) -> Optional[GlobalVar]:
        return None

    def callers(self, key: str) -> list[tuple[str, CallSite]]:
        out = []
        if key.startswith("cell:"):
            c = self.cell_by_hier.get(key[5:])
            if c and c["parent"]:
                pm = self.module_by_name.get(self.cell_by_hier[c["parent"]]["submodname"])
                inst = self._instance_of(pm, self.cell_by_hier[c["parent"]], c) if pm else None
                out.append(("cell:" + c["parent"], CallSite(callee_key=key, name=c["name"], loc=self._mkloc(inst["loc"] if inst else None),
                                                           kind="instance", args=list(inst["connections"]) if inst else [])))
        elif key.startswith("routine:"):
            for caller_key, cs in self.routine_callers.get(key[8:], []):
                out.append((caller_key, CallSite(callee_key=key, name=cs["name"], loc=self._mkloc(cs.get("loc")), kind="call",
                                                 args=list(cs.get("args", [])))))
        return out
