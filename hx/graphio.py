"""The one way to read a graph document.

Every reader (CLI, server, differ, MCP, exporter, `Graph.load`) goes through `load_graph_dict`, which
  * parses JSON with `values.parse_int_token`, so integers wider than JavaScript's 2**53 become canonical
    strings and a 5,000-digit legacy number never hits CPython's int<->str digit limit;
  * accepts the previous schema major (hx/1) and upgrades it IN MEMORY with `migrate_1_to_2`, attaching a
    `MigrationReport` under `meta.migration`; nothing on disk is touched;
  * refuses any other major.
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
    doc["schema"] = SCHEMA
    doc.setdefault("meta", {})["migration"] = rep.as_dict()
    return doc, rep


def _major(s: Any) -> tuple[str, str]:
    name, _, rest = str(s).partition("/")
    return name, rest.split(".")[0]


def load_graph_text(text: str) -> dict:
    doc = json.loads(text, parse_int=_values.parse_int_token)
    if not isinstance(doc, dict):
        raise SchemaError("graph document is not a JSON object")
    return doc


def upgrade(doc: dict) -> tuple[dict, Optional[MigrationReport]]:
    """Accept the current major as is, the previous one via in-memory migration, refuse the rest."""
    s = doc.get("schema")
    if s is None:
        raise SchemaError(f"graph has no 'schema' field (expected {SCHEMA!r})")
    name, major = _major(s)
    want_name, want_major = _major(SCHEMA)
    if name == want_name and major == want_major:
        return _values.json_safe(doc), None
    if name == want_name and major == "1":
        return migrate_1_to_2(doc)
    raise SchemaError(f"unsupported graph schema {s!r}: this hx reads {SCHEMA!r} (and upgrades hx/1 in memory)")


def load_graph_dict(path: str) -> dict:
    """Graph document from disk, normalized and (if needed) upgraded in memory. Raises SchemaError / OSError / ValueError."""
    with open(path, encoding="utf-8") as fh:
        doc = load_graph_text(fh.read())
    doc, _rep = upgrade(doc)
    return doc


def load_graph_with_report(path: str) -> tuple[dict, Optional[MigrationReport]]:
    with open(path, encoding="utf-8") as fh:
        doc = load_graph_text(fh.read())
    return upgrade(doc)
