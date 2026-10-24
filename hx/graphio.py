"""The one way to read a graph document.

Readers use the shared parsing/upgrading pipeline, normally through `load_graph_dict`, which
  * parses JSON with `values.parse_int_token`, so integers wider than JavaScript's 2**53 become canonical
    strings and a 5,000-digit legacy number never hits CPython's int<->str digit limit;
  * accepts older schema majors (hx/1 through hx/3) and upgrades them IN MEMORY through the `MIGRATIONS` chain,
    attaching one composed `MigrationReport` under `meta.migration`; nothing
    on disk is touched;
  * refuses any other major.

Snapshot consumers can call `load_graph_text` and `upgrade` on the exact bytes
they hash, avoiding a second file read.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from . import values as _values
from .model import SCHEMA, SchemaError

_VL_ESCAPE = re.compile(r"__(BRA|KET|DOT|0[0-9a-fA-F]{2})(?:__)?")
_MODULE_SCOPED_TYPE = re.compile(r"^(struct|union|enum|typedef) ([A-Za-z_][\w$]*)\.")   # scope.name, not pkg::name


def decode_verilator_name(s: str) -> str:
    """Verilator's identifier escapes back to source spelling: __BRA__ [ , __KET__ ] , __DOT__ . , __0XX hex."""
    def sub(m: "re.Match[str]") -> str:
        t = m.group(1)
        return {"BRA": "[", "KET": "]", "DOT": "."}.get(t) or chr(int(t[1:], 16))
    return _VL_ESCAPE.sub(sub, s) if "__" in s else s


def decode_sv_id(i: str) -> str:
    """Apply the decoding to the symbol component only (`<lang>:<path>::<symbol>`); paths stay literal."""
    head, sep, sym = i.partition("::")
    return head + sep + decode_verilator_name(sym) if sep else i


@dataclass
class MigrationReport:
    from_schema: str
    id_map: dict = field(default_factory=dict)          # lossless renames applied in memory (old -> new)
    needs_reextract: list = field(default_factory=list)  # [{"id", "reason"}] ids this file cannot settle
    notes: list = field(default_factory=list)

    @property
    def pending(self) -> bool:
        return bool(self.needs_reextract)

    def as_dict(self) -> dict:
        return {"from": self.from_schema, "renamed": len(self.id_map), "needs_reextract": self.needs_reextract[:200],
                "needs_reextract_total": len(self.needs_reextract), "notes": self.notes}


def _rename_ids(doc: dict, f) -> dict:
    """Rewrite every id-bearing field with f(old) -> new; returns {old: new} for the ids that changed."""
    changed: dict = {}

    def r(i):
        if not isinstance(i, str):
            return i
        n = f(i)
        if n != i:
            changed[i] = n
        return n

    for section in ("nodes", "types", "globals"):
        sec = doc.get(section) or {}
        doc[section] = {r(k): v for k, v in sec.items()}
        for v in doc[section].values():
            if isinstance(v, dict):
                if "id" in v:
                    v["id"] = r(v["id"])
                if "qualname" in v and isinstance(v["qualname"], str):
                    v["qualname"] = decode_verilator_name(v["qualname"])
                if isinstance(v.get("calls"), list):
                    v["calls"] = [r(x) for x in v["calls"]]
                if isinstance(v.get("used_by"), list):
                    v["used_by"] = [r(x) for x in v["used_by"]]
                for p in v.get("params") or []:
                    if isinstance(p, dict) and p.get("type_ref"):
                        p["type_ref"] = r(p["type_ref"])
                for fl in v.get("fields") or []:
                    if isinstance(fl, dict) and fl.get("type_ref"):
                        fl["type_ref"] = r(fl["type_ref"])
                if isinstance(v.get("returns"), dict) and v["returns"].get("type_ref"):
                    v["returns"]["type_ref"] = r(v["returns"]["type_ref"])
                if v.get("underlying_ref"):
                    v["underlying_ref"] = r(v["underlying_ref"])
                g = v.get("globals")
                if isinstance(g, dict):
                    for w in ("reads", "writes"):
                        if isinstance(g.get(w), list):
                            g[w] = [r(x) for x in g[w]]
    for e in doc.get("edges") or []:
        e["from"] = r(e.get("from"))
        if e.get("to"):
            e["to"] = r(e["to"])
    for u in doc.get("unresolved") or []:
        u["from"] = r(u.get("from"))
        if u.get("id"):
            u["id"] = r(u["id"])
    if doc.get("entry"):
        doc["entry"] = r(doc["entry"])
    return changed


def migrate_1_to_2(doc: dict) -> tuple[dict, MigrationReport]:
    """hx/1 -> hx/2 in memory. Lossless: Verilator escape decoding in SV symbol ids. Everything that hx/1 cannot
    settle (module-scoped SV type ids, which hx/2 identifies by layout; anonymous `anon@L<n>` ids; types whose
    nested refs were cut) is reported, never guessed: those ids stay as they are until `hx migrate` re-extracts."""
    rep = MigrationReport(from_schema=str(doc.get("schema")))
    doc = _values.json_safe(doc)
    if doc.get("lang") == "sv":
        rep.id_map = _rename_ids(doc, decode_sv_id)
        for tid, t in (doc.get("types") or {}).items():
            sym = tid.split("::", 1)[1] if "::" in tid else tid
            if sym.startswith("anon@L") or (isinstance(t, dict) and t.get("anonymous")):
                rep.needs_reextract.append({"id": tid, "reason": "anonymous type named by line number in hx/1"})
            elif _MODULE_SCOPED_TYPE.match(sym):
                rep.needs_reextract.append({"id": tid, "reason": "module-scoped type: hx/2 identifies it by layout and hx/1 "
                                                                 "kept no record of merged specializations"})
    types = doc.get("types") or {}
    for tid, t in types.items():
        for fl in (t.get("fields") or []) if isinstance(t, dict) else []:
            ref = fl.get("type_ref") if isinstance(fl, dict) else None
            if ref and ref not in types and not any(x["id"] == tid for x in rep.needs_reextract):
                rep.needs_reextract.append({"id": tid, "reason": f"nested type {ref} not in the graph (type depth)"})
                break
    if rep.id_map:
        rep.notes.append(f"{len(rep.id_map)} ids decoded from Verilator spelling")
    if rep.needs_reextract:
        rep.notes.append(f"{len(rep.needs_reextract)} ids need re-extraction (run `hx migrate`)")
    doc["schema"] = "hx/2"                       # each step stamps ITS destination; `upgrade` chains the steps
    doc.setdefault("meta", {})["migration"] = rep.as_dict()
    return doc, rep


_SYSTEM_PREFIXES = ("/usr/include", "/usr/lib", "/usr/local/include", "/opt/")


def _id_path(i: str) -> str:
    head = i.split("::", 1)[0]
    return head.split(":", 1)[1] if ":" in head else head


def migrate_2_to_3(doc: dict) -> tuple[dict, MigrationReport]:
    """hx/2 -> hx/3 in memory. Nothing is renamed (the hx/3 ids need symbol information the file does not hold);
    the report lists what `hx migrate` must re-extract: position-hashed LSP ids, module callers recorded as
    functions, hash-less nested LSP functions (found by extent containment, e.g. `Device._interp_with` inside
    `Device.evaluate`), C/C++ ids with non-system absolute paths (symlink spelling). Because a nested function whose
    parent is not in the graph cannot be detected, every LSP graph is flagged conservatively as a whole."""
    rep = MigrationReport(from_schema=str(doc.get("schema")))
    doc = _values.json_safe(doc)
    nodes = doc.get("nodes") or {}
    flagged: set[str] = set()

    def flag(i: str, reason: str) -> None:
        if i not in flagged:
            flagged.add(i)
            rep.needs_reextract.append({"id": i, "reason": reason})

    by_file: dict[str, list[tuple[int, int, str]]] = {}
    for nid, n in nodes.items():
        if n.get("precision") == "lsp" and isinstance(n.get("loc"), dict):
            loc = n["loc"]
            by_file.setdefault(loc.get("file") or "", []).append((loc.get("line") or 0, loc.get("end_line") or loc.get("line") or 0, nid))
    lsp_graph = False
    for nid, n in nodes.items():
        sym = nid.split("::", 1)[1] if "::" in nid else nid
        loc = n.get("loc") if isinstance(n.get("loc"), dict) else {}
        if n.get("precision") == "lsp":
            lsp_graph = True
            if "#" in sym:
                flag(nid, "position-hashed id: hx/3 identifies nested functions by their enclosing scope")
            elif n.get("kind") == "function" and str(n.get("name") or "").startswith("(module) "):
                flag(nid, "module caller recorded as a function: hx/3 makes it a `module` node spanning the file")
            else:
                line = loc.get("line") or 0
                for s, e, other in by_file.get(loc.get("file") or "", []):
                    if other != nid and s < line <= e:
                        flag(nid, f"nested in {other}: hx/3 includes the enclosing function in the id")
                        break
        elif n.get("lang") in ("c", "cpp"):
            p = _id_path(nid)
            if p.startswith("/") and not p.startswith(_SYSTEM_PREFIXES):
                flag(nid, "absolute path in id: hx/3 resolves symlinks to the project root")
    if lsp_graph:
        flag(str(doc.get("entry") or ""), "lsp graph: ids may change under hx/3 (nested scopes, module nodes, overload families): re-extract")
    if rep.needs_reextract:
        rep.notes.append(f"{len(rep.needs_reextract)} ids need re-extraction (run `hx migrate`)")
    doc["schema"] = "hx/3"
    doc.setdefault("meta", {})["migration"] = rep.as_dict()
    return doc, rep


def migrate_3_to_4(doc: dict) -> tuple[dict, MigrationReport]:
    """Preserve old bytes/IDs in memory; Rust identity corrections need source evidence."""
    rep = MigrationReport(from_schema="hx/3")
    if doc.get("lang") in ("rs", "rust"):
        rep.needs_reextract = [{"id": nid, "reason": "Rust impl identity and token rules changed in hx/4; re-extract"}
                               for nid in doc.get("nodes", {})]
        rep.notes.append("Rust annotations require source-based migration; old IDs are not guessed")
    doc["schema"] = "hx/4"
    return doc, rep


MIGRATIONS = {"1": migrate_1_to_2, "2": migrate_2_to_3, "3": migrate_3_to_4}


def _major(s: Any) -> tuple[str, str]:
    name, _, rest = str(s).partition("/")
    return name, rest.split(".")[0]


def load_graph_text(text: str) -> dict:
    doc = json.loads(text, parse_int=_values.parse_int_token)
    if not isinstance(doc, dict):
        raise SchemaError("graph document is not a JSON object")
    return doc


def upgrade(doc: dict) -> tuple[dict, Optional[MigrationReport]]:
    """Accept the current major as is; walk older majors through the migration chain (1 -> 2 -> 3) in memory,
    composing one report whose `from_schema` is the original; refuse anything else (a newer major included)."""
    s = doc.get("schema")
    if s is None:
        raise SchemaError(f"graph has no 'schema' field (expected {SCHEMA!r})")
    name, major = _major(s)
    want_name, want_major = _major(SCHEMA)
    if name == want_name and major == want_major:
        return _values.json_safe(doc), None
    if name != want_name or major not in MIGRATIONS:
        raise SchemaError(f"unsupported graph schema {s!r}: this hx reads {SCHEMA!r} (and upgrades {', '.join('hx/' + m for m in MIGRATIONS)} in memory)")
    rep: Optional[MigrationReport] = None
    guard = 0
    while major != want_major:
        step = MIGRATIONS.get(major)
        if step is None or guard > len(MIGRATIONS):
            raise SchemaError(f"no migration from hx/{major} to {SCHEMA!r}")
        doc, r = step(doc)
        if rep is None:
            rep = r
        else:
            composed = {k: r.id_map.get(v, v) for k, v in rep.id_map.items()}
            composed.update({k: v for k, v in r.id_map.items() if k not in rep.id_map and k not in composed.values()})
            rep.id_map = composed
            rep.needs_reextract.extend(x for x in r.needs_reextract if x not in rep.needs_reextract)
            rep.notes.extend(r.notes)
        _, major = _major(doc.get("schema"))
        guard += 1
    doc.setdefault("meta", {})["migration"] = rep.as_dict()
    return doc, rep


def load_graph_dict(path: str) -> dict:
    """Read a graph dictionary, normalizing values and upgrading schemas in memory.

    Args:
        path: UTF-8 graph JSON file.

    Returns:
        Current-major graph dictionary. The source file is not rewritten.

    Raises:
        OSError: The file cannot be read.
        ValueError: JSON is malformed, including SchemaError for unsupported schemas.
    """
    with open(path, encoding="utf-8") as fh:
        doc = load_graph_text(fh.read())
    doc, _rep = upgrade(doc)
    return doc


def load_graph_with_report(path: str) -> tuple[dict, Optional[MigrationReport]]:
    """Load a normalized graph plus an optional migration report.

    Returns a pair of the current-major dictionary and MigrationReport, or None
    for the report when no schema upgrade was needed. Writes no files. Raises
    OSError, ValueError, or SchemaError for the same failures as load_graph_dict.
    """
    with open(path, encoding="utf-8") as fh:
        doc = load_graph_text(fh.read())
    return upgrade(doc)
