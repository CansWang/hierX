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

HX_DIR = ".hx"
SOURCE_EXTS = {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".sv", ".svh", ".v", ".vh", ".rs", ".py", ".pyi", ".go", ".f"}
SKIP_DIRS = {".git", ".hx", ".venv", "venv", "node_modules", "target", "build", "obj_dir", "__pycache__", ".cache", "dist"}
EXTRACT_KEYS = ("depth", "type_depth", "include_callers", "include_system", "exclude", "max_nodes", "extra_args", "resource_dir",
                "lang", "compile_commands", "sv_files", "filelist", "top", "verilator", "lsp_cmd", "lsp_timeout", "jobs")


def hx_dir(root: str) -> str:
    return os.path.join(os.path.abspath(root), HX_DIR)


def config_path(root: str) -> str:
    return os.path.join(hx_dir(root), "config.toml")


def slug(entry: str) -> str:
    s = entry.replace("/", "__").replace(":", "__").replace("\\", "__")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def graph_path(root: str, entry: str) -> str:
    return os.path.join(hx_dir(root), "graphs", slug(entry) + ".json")


def history_dir(root: str, entry: str) -> str:
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
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")
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
            with open(p, encoding="utf-8") as fh:
                g = json.load(fh)
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
        with open(src, encoding="utf-8") as fh:
            g = json.load(fh)
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
    with open(dst, "wb") as fh:
        fh.write(payload)
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
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


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
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(parts) + "\n")
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
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if os.path.splitext(fn)[1] in exts:
                    p = os.path.join(dirpath, fn)
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
    os.makedirs(sdir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")
    return path, True
