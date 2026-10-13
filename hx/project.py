"""Project-level bookkeeping under <root>/.hx/:

  config.toml          tracked entry points (+ watch settings)
  graphs/<slug>.json   one graph per tracked entry (hx update / hx watch / hx mcp extract)
  history/<slug>/<generated>.json   previous graphs, pruned to `history` (default 20)
  last-diff.md         what the last update changed, for humans and agents
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from .diff import diff_graphs, render_markdown
from .fsutil import atomic_write

HX_DIR = ".hx"
SOURCE_EXTS = {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".sv", ".svh", ".v", ".vh", ".rs", ".py", ".pyi", ".go", ".f"}
# build descriptions that change what an extraction means, watched by name regardless of extension
WATCHED_NAMES = {"compile_commands.json", "Cargo.toml", "Cargo.lock", "pyrightconfig.json", "pyproject.toml", "CMakeLists.txt"}
SKIP_DIRS = {".git", ".hx", ".venv", "venv", "node_modules", "target", "build", "obj_dir", "__pycache__", ".cache", "dist"}
EXTRACT_KEYS = ("depth", "type_depth", "include_callers", "include_system", "exclude", "max_nodes", "extra_args", "resource_dir",
                "lang", "compile_commands", "sv_files", "filelist", "top", "verilator", "lsp_cmd", "lsp_timeout", "jobs")


def hx_dir(root: str) -> str:
    return os.path.join(os.path.abspath(root), HX_DIR)


def config_path(root: str) -> str:
    return os.path.join(hx_dir(root), "config.toml")


def _legacy_slug(entry: str) -> str:
    s = entry.replace("/", "__").replace(":", "__").replace("\\", "__")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def slug(entry: str) -> str:
    """File-name for an entry: readable prefix + a short hash of the exact entry text, so two different entries
    can never share a graph/history path (`a/b.c:f` vs `a__b.c:f` used to collide)."""
    from .ids import short_hash
    return _legacy_slug(entry)[:80] + "-" + short_hash(entry, 6)


def _migrate_legacy(root: str, entry: str) -> None:
    """Rename files written by hx < 0.2 (slug without hash) once, so tracked projects keep their history."""
    old, new = _legacy_slug(entry), slug(entry)
    if old == new:
        return
    for sub, ext in (("graphs", ".json"), ("history", "")):
        o = os.path.join(hx_dir(root), sub, old + ext)
        n = os.path.join(hx_dir(root), sub, new + ext)
        if os.path.exists(o) and not os.path.exists(n):
            try:
                os.replace(o, n)
            except OSError:
                pass


def graph_path(root: str, entry: str) -> str:
    _migrate_legacy(root, entry)
    return os.path.join(hx_dir(root), "graphs", slug(entry) + ".json")


def history_dir(root: str, entry: str) -> str:
    _migrate_legacy(root, entry)
    return os.path.join(hx_dir(root), "history", slug(entry))


# ---------------------------------------------------------------- config

def default_config() -> dict:
    return {"entries": [], "watch": {"interval": 2.0, "debounce": 1.0, "history": 20, "paths": []}}


def load_config(root: str) -> dict:
    p = config_path(root)
    cfg = default_config()
    if not os.path.exists(p):
        return cfg
    with open(p, "rb") as fh:
        data = tomllib.load(fh)
    cfg["entries"] = [dict(e) for e in data.get("entries", []) if isinstance(e, dict) and e.get("entry")]
    cfg["watch"].update({k: v for k, v in (data.get("watch") or {}).items()})
    return cfg


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v)  # TOML basic strings share JSON's escaping for our purposes
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"cannot write {type(v).__name__} to config.toml")


def save_config(root: str, cfg: dict) -> str:
    p = config_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    lines = ["# hx tracked entry points. Edit by hand or with `hx track`.", ""]
    w = cfg.get("watch") or {}
    if w:
        lines.append("[watch]")
        for k in ("interval", "debounce", "history", "paths"):
            if k in w and w[k] not in (None, []):
                lines.append(f"{k} = {_toml_value(w[k])}")
        lines.append("")
    for e in cfg.get("entries", []):
        lines.append("[[entries]]")
        lines.append(f"entry = {_toml_value(e['entry'])}")
        for k, v in e.items():
            if k == "entry" or v is None or v == [] or v == "":
                continue
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")
    atomic_write(p, "\n".join(lines).rstrip() + "\n")
    return p


def track(root: str, entry: str, **opts: Any) -> dict:
    """Add or replace a tracked entry. Returns the saved entry table."""
    cfg = load_config(root)
    table = {"entry": entry}
    for k, v in opts.items():
        if k in EXTRACT_KEYS and v not in (None, [], "", ()):
            table[k] = list(v) if isinstance(v, tuple) else v
    cfg["entries"] = [e for e in cfg["entries"] if e["entry"] != entry] + [table]
    save_config(root, cfg)
    return table


def untrack(root: str, entry: str) -> bool:
    cfg = load_config(root)
    before = len(cfg["entries"])
    cfg["entries"] = [e for e in cfg["entries"] if e["entry"] != entry]
    save_config(root, cfg)
    return len(cfg["entries"]) < before


# ---------------------------------------------------------------- graphs & history

def find_graphs(root: str) -> list[dict]:
    """Every graph the project knows: tracked graphs under .hx/graphs plus the ad-hoc .hx/graph.json."""
    out = []
    gdir = os.path.join(hx_dir(root), "graphs")
    paths = []
    if os.path.isdir(gdir):
        paths += sorted(os.path.join(gdir, f) for f in os.listdir(gdir) if f.endswith(".json"))
    default = os.path.join(hx_dir(root), "graph.json")
    if os.path.exists(default):
        paths.append(default)
    for p in paths:
        try:
            g = load_graph(p)
        except (OSError, ValueError):
            continue
        name = "graph" if p == default else os.path.splitext(os.path.basename(p))[0]
        out.append({"name": name, "path": p, "entry": g.get("entry"), "entry_arg": (g.get("meta") or {}).get("entry_arg"),
                    "generated": g.get("generated"), "nodes": len(g.get("nodes", {})), "lang": g.get("lang")})
    return out


def _safe_ts(ts: Optional[str]) -> str:
    ts = ts or time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    return re.sub(r"[^0-9TZ+-]", "-", ts)


def snapshot(root: str, entry: str, src_path: Optional[str] = None, keep: int = 20) -> Optional[str]:
    """Copy the current graph for `entry` into history (named by its `generated` stamp). Returns the snapshot path."""
    src = src_path or graph_path(root, entry)
    if not os.path.exists(src):
        return None
    try:
        g = load_graph(src)
    except (OSError, ValueError):
        return None
    hdir = history_dir(root, entry)
    os.makedirs(hdir, exist_ok=True)
    base = os.path.join(hdir, _safe_ts(g.get("generated")))
    dst = base + ".json"
    with open(src, "rb") as fh:
        payload = fh.read()
    n = 1
    while os.path.exists(dst):          # same second, different content → suffix; identical content → reuse
        with open(dst, "rb") as fh:
            if fh.read() == payload:
                return dst
        n += 1
        dst = f"{base}-{n}.json"
    atomic_write(dst, payload)
    prune_history(root, entry, keep)
    return dst


def prune_history(root: str, entry: str, keep: int) -> None:
    hdir = history_dir(root, entry)
    if not os.path.isdir(hdir):
        return
    files = sorted(f for f in os.listdir(hdir) if f.endswith(".json"))
    for f in files[:-keep] if keep > 0 else files:
        try:
            os.remove(os.path.join(hdir, f))
        except OSError:
            pass


def list_history(root: str, entry: str) -> list[dict]:
    hdir = history_dir(root, entry)
    if not os.path.isdir(hdir):
        return []
    out = []
    for f in sorted(os.listdir(hdir)):
        if f.endswith(".json"):
            out.append({"ts": f[:-5], "path": os.path.join(hdir, f)})
    return out


def resolve_history(root: str, entry: str, since: str = "prev") -> Optional[dict]:
    """'prev' → newest snapshot; an exact ts; or an ISO time → newest snapshot not after it."""
    hist = list_history(root, entry)
    if not hist:
        return None
    if since in ("prev", "last", "", None):
        return hist[-1]
    exact = [h for h in hist if h["ts"] == since or h["ts"] == _safe_ts(since)]
    if exact:
        return exact[0]
    key = _safe_ts(since)
    older = [h for h in hist if h["ts"] <= key]
    return older[-1] if older else hist[0]


def load_graph(path: str) -> dict:
    """Shared reader (hx/graphio): wide values normalized, hx/1 upgraded in memory."""
    from .graphio import load_graph_dict
    return load_graph_dict(path)


# ---------------------------------------------------------------- update

@dataclass
class UpdateResult:
    entry: str
    graph_path: str
    graph: Optional[dict] = None
    previous: Optional[str] = None       # snapshot path of the graph that was replaced
    diff: Optional[dict] = None
    markdown: str = ""
    error: Optional[str] = None
    seconds: float = 0.0

    @property
    def changed(self) -> bool:
        return bool(self.diff and self.diff["summary"]["any"])


def update(root: str, entries: Optional[Iterable[str]] = None, *, keep_history: Optional[int] = None,
           progress: Optional[Callable[[str], None]] = None) -> list[UpdateResult]:
    """Re-extract tracked entries (or the given ones), snapshot the previous graph and diff against it."""
    from .api import extract
    root = os.path.abspath(root)
    cfg = load_config(root)
    keep = keep_history if keep_history is not None else int(cfg["watch"].get("history", 20))
    tables = cfg["entries"]
    if entries:
        wanted = list(entries)
        tables = [e for e in tables if e["entry"] in wanted] + [{"entry": e} for e in wanted if e not in {t["entry"] for t in tables}]
    results: list[UpdateResult] = []
    for table in tables:
        entry = table["entry"]
        gp = graph_path(root, entry)
        res = UpdateResult(entry=entry, graph_path=gp)
        t0 = time.time()
        kwargs = {k: v for k, v in table.items() if k in EXTRACT_KEYS}
        try:
            if progress:
                progress(f"extracting {entry} …")
            graph = extract(entry, root=root, **kwargs)
            old = load_graph(gp) if os.path.exists(gp) else None
            if old is not None:
                res.previous = snapshot(root, entry, gp, keep)
                res.diff = diff_graphs(old, graph.to_dict())
                res.markdown = render_markdown(res.diff, graph.to_dict(), title=f"{entry}")
            else:
                res.markdown = f"# {entry}\nfirst extraction · {len(graph.nodes)} functions, {len(graph.types)} types, {len(graph.unresolved)} unresolved\n"
            graph.save(gp)
            res.graph = graph.to_dict()
        except Exception as e:  # noqa: BLE001 - one bad entry must not stop the others
            res.error = f"{type(e).__name__}: {e}"
            res.markdown = f"# {entry}\nextraction failed: {res.error}\n"
        res.seconds = round(time.time() - t0, 2)
        results.append(res)
    write_last_diff(root, results)
    return results


def write_last_diff(root: str, results: list[UpdateResult]) -> str:
    p = os.path.join(hx_dir(root), "last-diff.md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    parts = [f"<!-- hx update {stamp} -->"]
    changed = [r for r in results if r.changed or r.error or r.previous is None]
    if not results:
        parts.append("No tracked entries. Add one with `hx track <file>:<symbol>`.")
    elif not changed:
        parts.append(f"No structural changes in {len(results)} tracked entr{'y' if len(results) == 1 else 'ies'}.")
    for r in results:
        if r.changed or r.error or r.previous is None:
            parts.append(r.markdown.rstrip())
    atomic_write(p, "\n\n".join(parts) + "\n")
    return p


def summarize(results: list[UpdateResult]) -> str:
    """One line per entry, for terminals and hook output."""
    lines = []
    for r in results:
        if r.error:
            lines.append(f"✗ {r.entry}: {r.error}")
        elif r.previous is None:
            n = len((r.graph or {}).get("nodes", {}))
            lines.append(f"• {r.entry}: first extraction, {n} functions ({r.seconds}s)")
        elif r.changed:
            s = r.diff["summary"]
            lines.append(f"~ {r.entry}: functions +{s['nodes_added']} −{s['nodes_removed']} ~{s['nodes_changed']}, "
                         f"types ~{s['types_changed']}, edges +{s['edges_added']} −{s['edges_removed']} ({r.seconds}s)")
        else:
            lines.append(f"= {r.entry}: no structural change ({r.seconds}s)")
    return "\n".join(lines)


# ---------------------------------------------------------------- watch

def source_signature(root: str, paths: Optional[Iterable[str]] = None, exts: Iterable[str] = SOURCE_EXTS) -> dict[str, int]:
    """path -> mtime_ns for every source file under the watched paths (cheap enough to poll)."""
    exts = set(exts)
    bases = [os.path.join(root, p) for p in (paths or [])] or [root]
    sig: dict[str, int] = {}
    for base in bases:
        if os.path.isfile(base):
            try:
                sig[base] = os.stat(base).st_mtime_ns
            except OSError:
                pass
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            skipped = [d for d in dirnames if d in SKIP_DIRS or d.startswith(".")]
            dirnames[:] = [d for d in dirnames if d not in skipped]
            candidates = [os.path.join(dirpath, fn) for fn in filenames if os.path.splitext(fn)[1] in exts or fn in WATCHED_NAMES]
            for d in skipped:   # build dirs are not walked, but a compile_commands.json right inside one still counts
                candidates += [os.path.join(dirpath, d, n) for n in WATCHED_NAMES if os.path.exists(os.path.join(dirpath, d, n))]
            for p in candidates:
                try:
                    sig[p] = os.stat(p).st_mtime_ns
                except OSError:
                    pass
    return sig


def watch(root: str, *, interval: Optional[float] = None, debounce: Optional[float] = None, max_updates: Optional[int] = None,
          on_update: Optional[Callable[[list[UpdateResult]], None]] = None, run_first: bool = True,
          stop: Optional[Callable[[], bool]] = None) -> int:
    """Poll sources; after a quiet period following a change, run `update`. Returns the number of updates run."""
    root = os.path.abspath(root)
    cfg = load_config(root)
    interval = interval if interval is not None else float(cfg["watch"].get("interval", 2.0))
    debounce = debounce if debounce is not None else float(cfg["watch"].get("debounce", 1.0))
    paths = cfg["watch"].get("paths") or None
    sig = source_signature(root, paths)
    runs = 0
    if run_first:
        res = update(root)
        runs += 1
        if on_update:
            on_update(res)
        sig = source_signature(root, paths)
    pending_since: Optional[float] = None
    while True:
        if stop and stop():
            return runs
        if max_updates is not None and runs >= max_updates:
            return runs
        time.sleep(interval)
        cur = source_signature(root, paths)
        if cur != sig:
            sig = cur
            pending_since = time.time()
            continue
        if pending_since is not None and time.time() - pending_since >= debounce:
            pending_since = None
            res = update(root)
            runs += 1
            if on_update:
                on_update(res)
            sig = source_signature(root, paths)


# ---------------------------------------------------------------- Claude Code hook

def hook_snippet(event: str = "Stop", command: str = "hx update --quiet --hook", timeout: int = 300) -> dict:
    entry = {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
    if event == "PostToolUse":
        entry["matcher"] = "Edit|Write|MultiEdit|NotebookEdit"
    return {"hooks": {event: [entry]}}


def install_hook(root: str, event: str = "Stop", command: str = "hx update --quiet --hook", scope_dir: Optional[str] = None,
                 timeout: int = 300) -> tuple[str, bool]:
    """Merge the hook into <root>/.claude/settings.json (or scope_dir/settings.json). Returns (path, added)."""
    sdir = scope_dir or os.path.join(os.path.abspath(root), ".claude")
    path = os.path.join(sdir, "settings.json")
    settings: dict = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            try:
                settings = json.load(fh) or {}
            except ValueError as e:
                raise ValueError(f"{path} is not valid JSON: {e}") from e
    hooks = settings.setdefault("hooks", {})
    lst = hooks.setdefault(event, [])
    for group in lst:
        for hk in group.get("hooks", []):
            if hk.get("command") == command:
                return path, False
    lst.append(hook_snippet(event, command, timeout)["hooks"][event][0])
    atomic_write(path, json.dumps(settings, indent=2) + "\n")
    return path, True


# ---------------------------------------------------------------- migration (hx/1, hx/2 -> hx/3)

_LAYOUT_SUFFIX = re.compile(r"@[0-9a-f]{8}$")


def _type_shape(t: dict) -> tuple:
    return (t.get("kind"), t.get("size"), tuple((f.get("name"), f.get("bit_width"), f.get("bit_offset"), f.get("size"), f.get("offset"))
                                               for f in t.get("fields") or []))


def _split_id(i: str) -> tuple[str, str, str]:
    """`lang:path::qualname[#hash]` -> (lang, path, qualname without the hash)."""
    lang, _, rest = i.partition(":")
    path, _, qual = rest.partition("::")
    return lang, path, qual.split("#")[0]


def _trailing(qual: str) -> str:
    return re.split(r"\.|::", qual)[-1] if qual else qual


def _scope_compatible(old_qual: str, new_qual: str) -> bool:
    """GHOSTS: the new qualified name equals the old one, or the old one was bare and the new one adds a scope to it.
    A ghost has no location anchor of its own, so any wider rule would be a guess (review round 10)."""
    if new_qual == old_qual:
        return True
    bare = "." not in old_qual and "::" not in old_qual
    return bare and (new_qual.endswith("." + old_qual) or new_qual.endswith("::" + old_qual))


def _scope_compatible_node(old_qual: str, new_qual: str) -> bool:
    """NODES, anchored by (file, kind, name, line): the qualified name only guards against a different symbol at the
    same spot. Equal names, or the old leading scopes are a prefix of the new ones (`Device._interp_with` ->
    `Device.evaluate._interp_with`, bare `x` -> `outer.x`); `A.x` -> `B.A.x` is refused (review round 9)."""
    if new_qual == old_qual:
        return True
    op, np_ = re.split(r"\.|::", old_qual), re.split(r"\.|::", new_qual)
    return len(np_) > len(op) and op[-1] == np_[-1] and np_[:len(op) - 1] == op[:-1]


def _ghost_scope(qual: str) -> str:
    """The scope label a family record carries for a target: its container path, or `<module>` for a bare name."""
    sep = "::" if "::" in qual else "."
    parts = qual.split(sep)
    return sep.join(parts[:-1]) if len(parts) > 1 else "<module>"


def _ghost_sites(doc: dict, ghost_ids: set, node_map: dict) -> dict:
    """Every reference to each ghost id, keyed (mapped from, file, line, col): the unresolved records AND the edges
    whose target is a ghost (the saved hx/2 graphs carry call sites in edges that no unresolved record repeats)."""
    from collections import defaultdict
    sites: dict = defaultdict(set)
    for u in doc.get("unresolved") or []:
        if u.get("id"):
            loc = u.get("loc") or {}
            sites[u["id"]].add((node_map.get(u.get("from"), u.get("from")), loc.get("file"), loc.get("line"), loc.get("col")))
    for e in doc.get("edges") or []:
        if e.get("to") in ghost_ids:
            loc = e.get("loc") or {}
            sites[e["to"]].add((node_map.get(e.get("from"), e.get("from")), loc.get("file"), loc.get("line"), loc.get("col")))
    return sites


def map_node_ids(old: dict, new: dict, root: str) -> tuple[dict, dict, list[dict]]:
    """hx/2 -> hx/3 node and global ids, established from the fresh graph by LOCATION: an old node maps to the new node at
    the same (file, kind, name, line), with old absolute (symlink-spelled) files made root-relative first, an old
    `function` named `(module) …` matched against the new `module` node, and a nested LSP function (`x` or `x#hash`)
    matched only when its old qualified name is a dotted suffix of the new one (`outer.x`). Exactly one candidate maps;
    several are reported ambiguous and never applied; none is unmapped. Returns (mapped, ambiguous, unmapped)."""
    from collections import defaultdict
    from . import ids as _ids
    mapped: dict = {}
    ambiguous: dict = {}
    unmapped: list[dict] = []
    root_real = _ids.realpath(root)

    def norm(path: str) -> str:
        return _ids.rel(path, root_real) if path and os.path.isabs(path) else (path or "")

    for section in ("nodes", "globals"):
        new_sec = new.get(section) or {}
        index: dict = defaultdict(list)
        for nid, n in new_sec.items():
            loc = n.get("loc") or {}
            index[(norm(loc.get("file") or ""), n.get("kind"), n.get("name"), loc.get("line"))].append(nid)
        for oid, o in (old.get(section) or {}).items():
            if oid in new_sec:
                mapped[oid] = oid
                continue
            loc = o.get("loc") or {}
            kind, name = o.get("kind"), o.get("name")
            if section == "nodes" and kind == "function" and str(name or "").startswith("(module) "):
                kind = "module"
            cands = list(index.get((norm(loc.get("file") or ""), kind, name, loc.get("line")), []))
            if section == "nodes":
                oq = _split_id(oid)[2] or (o.get("qualname") or name or "")
                cands = [c for c in cands if _scope_compatible_node(oq, _split_id(c)[2])]
            if len(cands) == 1:
                mapped[oid] = cands[0]
            elif cands:
                ambiguous[oid] = sorted(cands)
            else:
                unmapped.append({"id": oid, "reason": f"no {section[:-1]} at the same file, kind, name and line in the new graph", "candidates": []})
    return mapped, ambiguous, unmapped


def map_ghost_ids(old: dict, new: dict, node_map: dict) -> tuple[dict, dict, list[dict]]:
    """hx/2 -> hx/3 unresolved (ghost) ids by CALL SITE with old-target identity checks (review rounds 4-6, 9, 11). An
    old ghost is identified by EVERY reference to it — unresolved records and edges — keyed (mapped from, file, line,
    col); the new ghost referenced from the same call site is the candidate. Accepted only when (a) language and
    declaring path agree, (b) the trailing name agrees and the new scope equals the old one or the old one was bare,
    (c) a hashed old id, or several old ids landing on one new id, carry verified overload-family metadata on the
    new record (`family.evidence == "@overload"`, scope equal to the target's, room for the distinct old ids), and
    (d) every call site of the old id yields that same single candidate: a site without a compatible target leaves
    the id unmapped, disagreeing sites make it ambiguous. There is no shortcut for an id that still exists: it goes
    through the same per-site rule, so an unchanged id with a conflicting site is reported, never assumed; a site
    that still references the id itself is an exact answer there, whatever scoped twins share the site."""
    from collections import defaultdict
    new_recs = {u["id"]: u for u in (new.get("unresolved") or []) if u.get("id")}
    new_by_site: dict = defaultdict(set)
    for nid, sites in _ghost_sites(new, set(new_recs), {}).items():
        for site in sites:
            new_by_site[site].add(nid)
    old_ids = {u["id"] for u in old.get("unresolved") or [] if u.get("id")}
    mapped: dict = {}
    ambiguous: dict = {}
    unmapped: list[dict] = []
    for oid, sites in _ghost_sites(old, old_ids, node_map).items():
        ol, op, oq = _split_id(oid)
        per_site: list[set] = []
        for site in sorted(sites, key=repr):
            cands = set()
            for cand in new_by_site.get(site, ()):
                nl, np_, nq = _split_id(cand)
                if nl == ol and np_ == op and _trailing(nq) == _trailing(oq) and _scope_compatible(oq, nq):
                    cands.add(cand)
            per_site.append({oid} if oid in cands else cands)        # the id itself at a site is an exact answer there
        targets = set().union(*per_site) if per_site else set()
        if not per_site or any(not c for c in per_site):
            unmapped.append({"id": oid, "reason": "a call site has no unresolved target with a compatible identity in the new graph",
                             "candidates": sorted(targets)})
        elif len(targets) > 1:
            ambiguous[oid] = sorted(targets)                       # (d) references disagree
        else:
            mapped[oid] = next(iter(targets))
    by_new: dict = defaultdict(list)
    for o, n in mapped.items():
        by_new[n].append(o)                                          # identity mappings count as landing there too
    for n, olds in by_new.items():
        changed = [o for o in olds if o != n]
        hashed = any("#" in o.split("::")[-1] for o in changed)
        if changed and (len(olds) > 1 or hashed):                   # (c) needs independent family evidence
            fam = (new_recs.get(n) or {}).get("family") or {}
            ok = fam.get("evidence") == "@overload" and len(olds) <= int(fam.get("size") or 0) \
                and fam.get("scope") == _ghost_scope(_split_id(n)[2])
            if not ok:
                for o in changed:
                    mapped.pop(o, None)
                    ambiguous[o] = [n]
    return mapped, ambiguous, unmapped


def map_type_ids(old: dict, new: dict, candidates: list[dict], user_map: dict) -> tuple[dict, list[dict]]:
    """Old type ids that the old schema could not settle -> new ids, established ONLY from the fresh graph: a type whose
    new id carries a `@<8hex>` suffix maps when exactly one new type shares its base id and its users (users compared
    after `user_map`, the node-id map, so hx/3 node renames do not hide a match); an anonymous `anon@L` type maps when
    exactly one new anonymous type has the identical layout and users. `candidates` are `{"id", "reason"}` items:
    the upgrade report's `needs_reextract` plus every old type id absent from the new graph. Anything else stays
    unmapped and is listed."""
    mapped: dict = {}
    unmapped: list[dict] = []
    nt = new.get("types") or {}
    ot = old.get("types") or {}
    users_of = lambda t: frozenset(user_map.get(u, u) for u in (t.get("used_by") or []))
    seen: set = set()
    for item in candidates:
        oid = item["id"]
        t = ot.get(oid)
        if t is None or oid in seen:
            continue
        seen.add(oid)
        sym = oid.split("::", 1)[1] if "::" in oid else oid
        if sym.startswith("anon@L") or t.get("anonymous"):
            related = [nid for nid, n in nt.items() if n.get("anonymous") and _type_shape(n) == _type_shape(t)]
            how = "anonymous type with identical layout and users"
        else:
            related = [nid for nid, n in nt.items() if _LAYOUT_SUFFIX.sub("", nid) == oid]
            how = "module-scoped type with the same base id and users"
        cands = [nid for nid in related if users_of(nt[nid]) == users_of(t)]
        if len(cands) == 1:
            mapped[oid] = cands[0]
        else:
            unmapped.append({"id": oid, "reason": item["reason"], "candidates": sorted(related)[:4], "note": f"no unique {how}"})
    return mapped, unmapped


def _invalidated_ids(old: dict, new: dict, node_map: dict) -> list[str]:
    """New node ids whose `verified_body_hash` cannot carry over: the old node was a module caller recorded as a
    `function` (hx/2 hashed one line, hx/3 hashes the whole file) or the node's kind changed — whatever happened to
    the id, which for a module node is usually unchanged (review round 9)."""
    out: set[str] = set()
    on, nn = old.get("nodes") or {}, new.get("nodes") or {}
    for k, v in node_map.items():
        o, n = on.get(k) or {}, nn.get(v) or {}
        if not o or not n:
            continue
        module_caller = o.get("kind") == "function" and str(o.get("name") or "").startswith("(module) ")
        if module_caller or o.get("kind") != n.get("kind"):
            out.add(v)
    return sorted(out)


def migrate(root: str, *, keep_history: Optional[int] = None, progress: Optional[Callable[[str], None]] = None) -> dict:
    """The one persistent older-schema -> current-schema operation (hx/1 or hx/2 -> hx/3). Every tracked entry is
    re-extracted into a staging directory; only
    when ALL succeed are the graphs committed (previous ones snapshotted), and annotations rewritten once under the
    file lock with a one-time backup. Any failure leaves graphs, history, annotations and backups byte-for-byte unchanged."""
    import shutil
    from . import annotations as ann_mod
    from .api import extract
    from .graphio import load_graph_with_report
    root = os.path.abspath(root)
    cfg = load_config(root)
    keep = keep_history if keep_history is not None else int(cfg["watch"].get("history", 20))
    staging = os.path.join(hx_dir(root), f"staging-{os.getpid()}")
    out: dict = {"status": "noop", "entries": [], "failed": [], "id_map": {}, "ambiguous": {}, "unmapped": [], "invalidated": [],
                 "annotations": None}
    staged: list[tuple[str, str, str, dict, list, dict]] = []
    invalidate: list[str] = []
    majors: set[str] = set()
    try:
        os.makedirs(staging, exist_ok=True)
        for table in cfg["entries"]:
            entry = table["entry"]
            gp = graph_path(root, entry)
            kwargs = {k: v for k, v in table.items() if k in EXTRACT_KEYS}
            old_doc, rep = (None, None)
            if os.path.exists(gp):
                try:
                    old_doc, rep = load_graph_with_report(gp)
                except Exception as e:  # noqa: BLE001
                    out["failed"].append({"entry": entry, "error": f"cannot read {gp}: {type(e).__name__}: {e}"})
                    continue
            if progress:
                progress(f"re-extracting {entry} …")
            try:
                graph = extract(entry, root=root, **kwargs)
            except Exception as e:  # noqa: BLE001
                out["failed"].append({"entry": entry, "error": f"{type(e).__name__}: {e}"})
                continue
            sp = os.path.join(staging, os.path.basename(gp))
            graph.save(sp)
            id_map: dict = {}
            unmapped: list = []
            entry_ambiguous: dict = {}
            if old_doc is not None:
                nd = graph.to_dict()
                lossless = dict(rep.id_map) if rep else {}
                id_map.update(lossless)
                node_map, amb_nodes, unm_nodes = map_node_ids(old_doc, nd, root)
                id_map.update({k: v for k, v in node_map.items() if k != v})
                ghost_map, amb_ghosts, unm_ghosts = map_ghost_ids(old_doc, nd, node_map)
                id_map.update({k: v for k, v in ghost_map.items() if k != v})
                listed = {x["id"] for x in (rep.needs_reextract if rep else [])}
                candidates = list(rep.needs_reextract if rep else []) + \
                    [{"id": t, "reason": "id absent after hx/3 rekeying"} for t in (old_doc.get("types") or {}) if t not in (nd.get("types") or {}) and t not in listed]
                by_type, unm_types = map_type_ids(old_doc, nd, candidates, {**lossless, **node_map})
                id_map.update(by_type)
                unmapped = unm_nodes + unm_ghosts + unm_types
                entry_ambiguous = {**amb_nodes, **amb_ghosts}
                invalidate += _invalidated_ids(old_doc, nd, node_map)   # module callers: the whole-file hash means something new
                if rep:
                    majors.add(rep.from_schema)
                elif old_doc.get("schema"):
                    majors.add(str(old_doc["schema"]))
            staged.append((entry, gp, sp, id_map, unmapped, entry_ambiguous))
            out["entries"].append({"entry": entry, "renamed": len(id_map), "unmapped": len(unmapped), "ambiguous": len(entry_ambiguous),
                                   "was_schema": (rep.from_schema if rep else None) or (old_doc or {}).get("schema")})
        if out["failed"]:
            out["status"] = "failed"
            return out
        merged: dict = {}
        ambiguous: dict = {}
        for entry, gp, sp, id_map, unmapped, entry_ambiguous in staged:
            for k, v in id_map.items():
                if k in merged and merged[k] != v:
                    ambiguous.setdefault(k, {merged[k]}).add(v)
                else:
                    merged.setdefault(k, v)
            for k, vs in entry_ambiguous.items():
                ambiguous.setdefault(k, set()).update(vs)
            out["unmapped"] += [dict(u, entry=entry) for u in unmapped]
        for k in ambiguous:
            merged.pop(k, None)
        out["ambiguous"] = {k: sorted(v) for k, v in ambiguous.items()}
        # commit: snapshot previous graphs, move staged graphs into place, then annotations (backup first, inside)
        for entry, gp, sp, _m, _u, _a in staged:
            if os.path.exists(gp):
                snapshot(root, entry, gp, keep)
            os.makedirs(os.path.dirname(gp), exist_ok=True)
            os.replace(sp, gp)
        out["id_map"] = merged
        out["invalidated"] = sorted(set(invalidate))
        from_major = min((m.split("/")[-1].split(".")[0] for m in majors if "/" in m), default="2")
        ann_path = os.path.join(hx_dir(root), "annotations.json")
        if os.path.exists(ann_path):
            if merged or invalidate:
                out["annotations"] = ann_mod.migrate_file(ann_path, merged, from_schema=f"hx/{from_major}",
                                                          backup_suffix=f".bak-hx{from_major}", invalidate=sorted(set(invalidate)))
            else:
                out["annotations"] = {"status": "noop", "renamed": 0}
        out["status"] = "migrated" if staged else "noop"
        return out
    finally:
        shutil.rmtree(staging, ignore_errors=True)
