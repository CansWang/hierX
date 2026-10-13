"""Human-owned annotation layer, kept apart from the generated graph.

annotations.json (schema hx-ann/1):
  nodes{id: {note, tags[], verified_body_hash, collapsed, params{name: {dir, note}}}}
  types{id: {note, fields{name: {note}}}}
  globals{id: {note}}
  view{hidden[], pinned_positions{id: {x, y}}}
One file per project (next to graph.json), shared by every entry point, keyed
by stable ids so it survives regeneration.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

from .fsutil import file_lock

SCHEMA = "hx-ann/1"
_lock = threading.Lock()


def empty() -> dict:
    return {"schema": SCHEMA, "nodes": {}, "types": {}, "globals": {}, "view": {"hidden": [], "pinned_positions": {}}, "meta": {}}


def normalize(doc: Any) -> dict:
    """Coerce an arbitrary document into a well-formed annotations dict (never raises on shape)."""
    out = empty()
    if not isinstance(doc, dict):
        return out
    for key in ("nodes", "types", "globals"):
        v = doc.get(key)
        if isinstance(v, dict):
            out[key] = {k: val for k, val in v.items() if isinstance(val, dict)}
    view = doc.get("view")
    if isinstance(view, dict):
        hidden = view.get("hidden")
        if isinstance(hidden, list):
            out["view"]["hidden"] = [h for h in hidden if isinstance(h, str)]
        pos = view.get("pinned_positions")
        if isinstance(pos, dict):
            out["view"]["pinned_positions"] = {k: v for k, v in pos.items() if isinstance(v, dict)}
    meta = doc.get("meta")
    if isinstance(meta, dict):                       # e.g. {"migrated": {"from": "hx/1", "map_hash": …, "at": …}}
        mig = meta.get("migrated")
        if isinstance(mig, dict) and isinstance(mig.get("map_hash"), str):
            out["meta"]["migrated"] = {"from": str(mig.get("from", "")), "map_hash": mig["map_hash"], "at": str(mig.get("at", ""))}
    return out


def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return normalize(json.load(fh))
    except FileNotFoundError:
        return empty()
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e


def save(path: str, doc: dict) -> None:
    doc = normalize(doc)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7386 JSON merge patch: dicts merge recursively, None deletes, anything else replaces."""
    if not isinstance(patch, dict):
        return patch
    if not isinstance(target, dict):
        target = {}
    else:
        target = dict(target)
    for k, v in patch.items():
        if v is None:
            target.pop(k, None)
        else:
            target[k] = merge_patch(target.get(k), v)
    return target


def prune_empty(doc: dict) -> dict:
    """Drop entries that became empty after deletions (recursively) so the file stays readable."""
    doc = normalize(doc)
    for key in ("nodes", "types", "globals"):
        doc[key] = {k: _prune(v) for k, v in doc[key].items() if _nonempty(v)}
    return doc


def _prune(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _prune(x) for k, x in v.items() if _nonempty(x)}
    return v


def _nonempty(v: Any) -> bool:
    if isinstance(v, dict):
        return any(_nonempty(x) for x in v.values())
    if isinstance(v, (list, str)):
        return len(v) > 0
    return v is not None and v is not False


def patch_file(path: str, patch: dict) -> dict:
    """load → merge → save under a thread lock AND a cross-process file lock (`hx serve`, `hx mcp` and the CLI
    may all write the same annotations.json); returns the new document."""
    with _lock, file_lock(path):
        doc = load(path)
        doc = prune_empty(merge_patch(doc, patch))
        save(path, doc)
        return doc


def replace_file(path: str, doc: dict) -> dict:
    with _lock, file_lock(path):
        doc = prune_empty(doc)
        save(path, doc)
        return doc


def map_hash(id_map: dict) -> str:
    import hashlib
    h = hashlib.sha1()
    for k in sorted(id_map):
        h.update(k.encode("utf-8", "replace") + b"\0" + str(id_map[k]).encode("utf-8", "replace") + b"\n")
    return h.hexdigest()[:16]


def migrate_keys(doc: dict, id_map: dict) -> tuple[dict, dict]:
    """Rewrite annotation keys old -> new (nodes/types/globals, view.hidden, pinned_positions). When both the old and
    the new key hold data the new key's fields win, old-only fields fill in, and the clash is reported. Returns
    (document, report{renamed, conflicts, untouched})."""
    doc = normalize(doc)
    report = {"renamed": 0, "conflicts": [], "untouched": 0}
    for section in ("nodes", "types", "globals"):
        sec = doc[section]
        for old, new in id_map.items():
            if old not in sec or old == new:
                continue
            val = sec.pop(old)
            if new in sec:
                merged = dict(val)
                for k, v in sec[new].items():
                    if k in merged and merged[k] != v:
                        report["conflicts"].append({"section": section, "old": old, "new": new, "field": k})
                    merged[k] = v
                sec[new] = merged
            else:
                sec[new] = val
            report["renamed"] += 1
    view = doc["view"]
    view["hidden"] = [id_map.get(x, x) for x in view["hidden"]]
    pos = view["pinned_positions"]
    for old, new in id_map.items():
        if old in pos and old != new:
            pos.setdefault(new, pos.pop(old))
            if old in pos:
                del pos[old]
    for section in ("nodes", "types", "globals"):
        report["untouched"] += sum(1 for k in doc[section] if k not in id_map.values())
    return doc, report


def migrate_file(path: str, id_map: dict, *, from_schema: str = "hx/1", backup_suffix: str = ".bak-hx1",
                 invalidate: Optional[list[str]] = None) -> dict:
    """Persistent key migration: one locked, atomic rewrite; a backup written once and never overwritten; a
    `meta.migrated` marker (kept by normalize/save) makes a repeat with the same map a no-op. `invalidate` lists
    (new) node ids whose `verified_body_hash` no longer means anything (hx/3 module nodes hash the whole file)."""
    import shutil
    import time
    mh = map_hash({**id_map, **{f"!{i}": "invalidate" for i in (invalidate or [])}})
    with _lock, file_lock(path):
        doc = load(path)
        done = doc["meta"].get("migrated") or {}
        if done.get("map_hash") == mh:
            return {"status": "noop", "map_hash": mh, "renamed": 0, "conflicts": [], "backup": path + backup_suffix}
        backup = path + backup_suffix
        if os.path.exists(path) and not os.path.exists(backup):
            shutil.copyfile(path, backup)
        doc, report = migrate_keys(doc, id_map)
        report["invalidated"] = []
        for nid in invalidate or []:
            node = doc["nodes"].get(nid)
            if isinstance(node, dict) and node.pop("verified_body_hash", None) is not None:
                report["invalidated"].append(nid)
        doc["meta"]["migrated"] = {"from": from_schema, "map_hash": mh, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        save(path, prune_empty(doc))
        report.update({"status": "migrated", "map_hash": mh, "backup": backup})
        return report


def effective_dir(node: dict, ann: dict, param_name: str) -> tuple[str, str]:
    """(dir, dir_source) for a param after applying a user override."""
    override = (((ann.get("nodes") or {}).get(node["id"]) or {}).get("params") or {}).get(param_name) or {}
    for p in node.get("params", []):
        if p["name"] == param_name:
            if override.get("dir"):
                return override["dir"], "user"
            return p["dir"], p.get("dir_source", "heuristic")
    raise KeyError(param_name)
