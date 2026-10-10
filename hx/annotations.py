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
from typing import Any

from .fsutil import file_lock

SCHEMA = "hx-ann/1"
_lock = threading.Lock()


def empty() -> dict:
    return {"schema": SCHEMA, "nodes": {}, "types": {}, "globals": {}, "view": {"hidden": [], "pinned_positions": {}}}


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


def effective_dir(node: dict, ann: dict, param_name: str) -> tuple[str, str]:
    """(dir, dir_source) for a param after applying a user override."""
    override = (((ann.get("nodes") or {}).get(node["id"]) or {}).get("params") or {}).get(param_name) or {}
    for p in node.get("params", []):
        if p["name"] == param_name:
            if override.get("dir"):
                return override["dir"], "user"
            return p["dir"], p.get("dir_source", "heuristic")
    raise KeyError(param_name)
