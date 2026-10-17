"""Generic LSP frontend: any language server with call hierarchy (rust-analyzer, pyright, clangd, gopls ...).

Precision is `lsp`: signatures come from hover text, struct fields from documentSymbol (+ hover per field),
no sizes/offsets, no globals, and calls through function pointers/closures are invisible to the server.
Keys are source positions ("<uri>#<line>:<char>"), resolved lazily, so only what the traversal asks for
costs a round trip.
"""
from __future__ import annotations

import copy
import json
import os
import queue
import re
import subprocess
import threading
import time
from typing import Any, Optional
from urllib.parse import unquote, urlparse
from urllib.request import pathname2url

from .. import ids as _ids
from ..model import Loc, Node, Param, TypeUse, GlobalRefs, TypeDef, Field, Enumerator, GlobalVar
from .base import Frontend, FunctionRecord, DeclRecord, TypeRecord, CallSite, EntryNotFound, FrontendError

SERVERS: dict[str, dict] = {
    "rust":   {"cmd": ["rust-analyzer"], "language_id": "rust", "exts": [".rs"], "lang": "rs", "sep": "::"},
    "python": {"cmd": ["pyright-langserver", "--stdio"], "language_id": "python", "exts": [".py", ".pyi"], "lang": "py", "sep": "."},
    "go":     {"cmd": ["gopls"], "language_id": "go", "exts": [".go"], "lang": "go", "sep": "."},
    "clangd": {"cmd": ["clangd", "--background-index"], "language_id": "cpp", "exts": [".c", ".cc", ".cpp", ".h", ".hpp"], "lang": "cpp", "sep": "::"},
}
EXT_TO_SERVER = {ext: name for name, cfg in SERVERS.items() for ext in cfg["exts"] if name != "clangd"}

_PRIMITIVE = re.compile(r"^(?:&\s*(?:mut\s+)?)?(?:int|str|bytes|bool|float|None|object|usize|isize|u\d+|i\d+|f\d+|char|String|\[u8\]|str|Self|Literal\[.*\])$")

SK = {5: "class", 6: "method", 9: "constructor", 10: "enum", 11: "interface", 12: "function", 13: "variable", 7: "property",
      8: "field", 22: "enum_member", 23: "struct", 2: "module", 3: "namespace", 19: "object", 26: "type_parameter"}
FUNC_KINDS = {6, 9, 12}
TYPE_KINDS = {5, 10, 11, 23, 26}
# Module, Namespace, Class, Method, Enum, Interface, Function, Object, Struct: enclosing FUNCTIONS are part of a
# qualified name too (review finding H2: two `_emit_global` helpers under different outer functions are distinct).
CONTAINER_KINDS = {2, 3, 5, 6, 10, 11, 12, 19, 23}
FIELD_KINDS = {7, 8, 13, 22}


def path_to_uri(p: str) -> str:
    return "file://" + pathname2url(os.path.abspath(p))


def uri_to_path(u: str) -> str:
    return unquote(urlparse(u).path)


# ============================================================ JSON-RPC client

class LspError(FrontendError):
    pass


class LspClient:
    def __init__(self, cmd: list[str], root: str, verbose: bool = False, log_path: Optional[str] = None):
        self.cmd = cmd
        self.root = root
        self.verbose = verbose
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=open(log_path, "ab") if log_path else subprocess.DEVNULL, cwd=root)
        except FileNotFoundError:
            raise LspError(f"language server not found: {cmd[0]!r} (install it or pass --lsp-cmd)")
        self._id = 0
        self._pending: dict[int, queue.Queue] = {}
        self._lock = threading.Lock()
        self.notifications: queue.Queue = queue.Queue()
        self.progress_active: set[Any] = set()
        self.progress_seen = False
        self.quiescent: Optional[bool] = None
        self.caps: dict = {}
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # -- transport ---------------------------------------------------------
    def _send(self, msg: dict) -> None:
        data = json.dumps(msg).encode("utf-8")
        with self._lock:
            try:
                self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError):
                raise LspError(f"language server {self.cmd[0]} exited unexpectedly")

    def _read_loop(self) -> None:
        out = self.proc.stdout
        try:
            while True:
                headers = {}
                while True:
                    line = out.readline()
                    if not line:
                        return
                    if line in (b"\r\n", b"\n"):
                        break
                    k, _, v = line.decode("ascii", "replace").partition(":")
                    headers[k.strip().lower()] = v.strip()
                n = int(headers.get("content-length", "0"))
                body = out.read(n) if n else b""
                try:
                    msg = json.loads(body.decode("utf-8", "replace"))
                except ValueError:
                    continue
                self._dispatch(msg)
        finally:
            for q in list(self._pending.values()):
                q.put({"error": {"code": -1, "message": "server exited"}})

    def _dispatch(self, msg: dict) -> None:
        if "id" in msg and "method" in msg:          # server -> client request
            self._answer(msg)
        elif "id" in msg:                            # response
            q = self._pending.pop(msg["id"], None)
            if q is not None:
                q.put(msg)
        else:                                        # notification
            m = msg.get("method")
            p = msg.get("params") or {}
            if m == "$/progress":
                kind = (p.get("value") or {}).get("kind")
                tok = p.get("token")
                if kind == "begin":
                    self.progress_active.add(tok)
                    self.progress_seen = True
                elif kind == "end":
                    self.progress_active.discard(tok)
            elif m == "experimental/serverStatus":
                self.quiescent = bool(p.get("quiescent"))
            self.notifications.put(msg)

    def _answer(self, msg: dict) -> None:
        m = msg["method"]
        result: Any = None
        if m == "workspace/configuration":
            result = [None for _ in (msg.get("params") or {}).get("items", [])]
        elif m == "workspace/workspaceFolders":
            result = [{"uri": path_to_uri(self.root), "name": os.path.basename(self.root)}]
        elif m == "window/workDoneProgress/create":
            tok = (msg.get("params") or {}).get("token")
            if tok is not None:
                pass
            result = None
        self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    # -- api -----------------------------------------------------------------
    def request(self, method: str, params: Any, timeout: float = 60.0) -> Any:
        with self._lock:
            self._id += 1
            rid = self._id
        q: queue.Queue = queue.Queue()
        self._pending[rid] = q
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            resp = q.get(timeout=timeout)
        except queue.Empty:
            self._pending.pop(rid, None)
            raise LspError(f"{method}: no response from {self.cmd[0]} within {timeout:.0f}s")
        if "error" in resp:
            err = resp["error"]
            raise LspError(f"{method}: {err.get('message')} (code {err.get('code')})")
        return resp.get("result")

    def notify(self, method: str, params: Any) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def initialize(self) -> None:
        caps = {
            "general": {"positionEncodings": ["utf-8", "utf-16"]},
            "textDocument": {
                "hover": {"contentFormat": ["markdown", "plaintext"]},
                "callHierarchy": {"dynamicRegistration": False},
                "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                "definition": {"linkSupport": True}, "typeDefinition": {"linkSupport": True},
                "synchronization": {"didSave": False},
            },
            "workspace": {"configuration": True, "workspaceFolders": True},
            "window": {"workDoneProgress": True},
            "experimental": {"serverStatusNotification": True},
        }
        res = self.request("initialize", {
            "processId": os.getpid(), "rootUri": path_to_uri(self.root), "rootPath": self.root,
            "capabilities": caps, "workspaceFolders": [{"uri": path_to_uri(self.root), "name": os.path.basename(self.root)}],
            "initializationOptions": {},
        }, timeout=60)
        self.caps = (res or {}).get("capabilities", {})
        self.position_encoding = self.caps.get("positionEncoding", "utf-16")
        self.notify("initialized", {})

    def wait_ready(self, timeout: float) -> None:
        """Wait for indexing to settle: serverStatus quiescent (rust-analyzer) or no progress for 0.6s."""
        t0 = time.time()
        quiet_since = None
        while time.time() - t0 < timeout:
            if self.quiescent is True:
                return
            if self.quiescent is False:
                time.sleep(0.1)
                continue
            if self.progress_active:
                quiet_since = None
            else:
                quiet_since = quiet_since or time.time()
                if time.time() - quiet_since > (0.6 if self.progress_seen else 1.5):
                    return
            time.sleep(0.05)
        raise LspError(f"{self.cmd[0]} indexing did not settle within {timeout:g}s")

    def shutdown(self) -> None:
        try:
            self.request("shutdown", None, timeout=5)
            self.notify("exit", None)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            self.proc.kill()


# ============================================================ signature parsing

def _code_blocks(hover: Any) -> list[str]:
    if hover is None:
        return []
    c = hover.get("contents") if isinstance(hover, dict) else hover
    texts: list[str] = []
    if isinstance(c, dict):
        texts.append(c.get("value", ""))
    elif isinstance(c, list):
        for x in c:
            texts.append(x.get("value", "") if isinstance(x, dict) else str(x))
    elif isinstance(c, str):
        texts.append(c)
    blocks: list[str] = []
    for t in texts:
        found = re.findall(r"```[a-zA-Z0-9_+-]*\n(.*?)```", t, flags=re.S)
        blocks += [b.strip() for b in found] if found else ([t.strip()] if t.strip() else [])
    return blocks


def split_top(text: str, sep: str = ",", lang: str = "py") -> list[str]:
    """Top-level split that never cuts inside a string literal (review findings H1/H3). `<`/`>` count as
    brackets only for Rust generics; in Python they are comparison operators."""
    return _ids.split_top(text, lang, sep=sep, angle=(lang == "rs"))


def parse_signature(sig: str, lang: str) -> tuple[list[dict], Optional[str]]:
    """'pub fn f(a: &mut T, b: &[u8]) -> R' / '(function) def f(a: int, *, b: str = "x") -> None' -> params, return.
    Token based (review finding H3): whitespace is squashed only BETWEEN tokens, the parameter list is matched over
    brackets, and `,` `=` `:` split only at the top level, so a default such as `","` cannot create a parameter."""
    sig = _ids.squash_ws(sig, lang)
    m = re.search(r"\b(?:fn|def|func)\b\s*[^(]*?\(", sig)
    start = m.end() if m else sig.find("(") + 1
    if lang == "rs":
        toks = _ids.lex(sig, "rs")
        begun, angle_depth = False, 0
        for tok in toks:
            if tok.text == "fn":
                begun = True
                continue
            if not begun:
                continue
            if tok.text == "<":
                angle_depth += 1
            elif tok.text in (">", ">>"):
                angle_depth = max(0, angle_depth - len(tok.text))
            elif tok.text == "(" and not angle_depth:
                start = tok.end
                break
    if start <= 0:
        return [], None
    span = _ids.paren_span(sig[start - 1:], lang)
    if span is None:
        inner, rest = sig[start:], ""
    else:
        close = start - 1 + span[1]
        inner, rest = sig[start:close], sig[close + 1:]
    ret = None
    rm = re.search(r"->\s*(.+?)(?:\s+where\b.*)?$", rest)
    if rm:
        ret = rm.group(1).strip().rstrip(":").strip()
    rs = lang == "rs"
    params = []
    for raw in _ids.split_top(inner, lang, angle=rs):
        if raw in ("*", "/", "..."):
            continue
        p, default = raw, None
        if lang == "py":
            p, default = _ids.partition_top(raw, lang, "=")
        if rs:
            mm = re.match(r"^(&\s*(?:'\w+\s+)?(?:mut\s+)?)?(self)\s*(?::\s*(.+))?$", p)
            if mm:
                typ = mm.group(3) or (re.sub(r"\s+", " ", (mm.group(1) or "")).strip() + " Self").strip()
                params.append({"name": "self", "type": typ, "dir": "inout" if "mut" in (mm.group(1) or "") or (mm.group(3) and "mut" in mm.group(3)) else "in"})
                continue
            name, typ = _ids.partition_top(p, lang, ":", angle=True)
            name = re.sub(r"^(mut|ref)\s+", "", name.strip())
            typ = (typ or "").strip() or "?"
            d = "inout" if re.match(r"^&\s*(?:'\w+\s+)?mut\b", typ) or typ.startswith("*mut") else "in"
            params.append({"name": name, "type": typ, "dir": d})
        else:
            name, typ = _ids.partition_top(p, lang, ":")
            name = name.strip()
            typ = (typ or "").strip() or "?"
            if name.startswith("**"):
                typ = f"dict[str, {typ}]" if typ != "?" else "dict"
            elif name.startswith("*"):
                typ = f"tuple[{typ}, ...]" if typ != "?" else "tuple"
            d = {"name": name.lstrip("*"), "type": typ, "dir": "in"}
            if default:
                d["default"] = default
            params.append(d)
    return params, ret


# ============================================================ Frontend

class LspFrontend(Frontend):
    def __init__(self, root: str, *, server: str = "rust", cmd: list[str] | None = None, timeout: float = 90.0,
                 verbose: bool = False, log_path: Optional[str] = None):
        if server not in SERVERS:
            raise FrontendError(f"unknown LSP server profile {server!r}; choose from {sorted(SERVERS)}")
        self.root = _ids.realpath(root)
        self.profile = SERVERS[server]
        self.server = server
        self.cmd = cmd or self.profile["cmd"]
        self.lang = self.profile["lang"]
        self.sep = self.profile["sep"]
        self.timeout = timeout
        self.verbose = verbose
        self.log_path = log_path
        self.client: Optional[LspClient] = None
        self.opened: set[str] = set()
        self.src_cache: dict[str, list[str]] = {}
        self.items: dict[str, dict] = {}          # key -> CallHierarchyItem
        self.symbols_cache: dict[str, list] = {}  # uri -> flattened symbols
        self.types: dict[str, dict] = {}          # type key -> summary
        self.ids: dict[str, str] = {}
        self._used_ids: set[str] = set()         # ids handed out so far (O(1) collision check in _register)
        self._source_less: set[str] = set()
        self._nonfunctions: set[str] = set()
        self._fn_cache: dict[str, FunctionRecord] = {}   # key -> record (review finding H4); handed out as copies
        self._caller_cache: dict[str, FunctionRecord] = {}
        self._families: dict[str, dict] = {}     # key of a collapsed stub overload family -> {size, evidence, scope}
        self.type_ids: dict[str, str] = {}
        self.stats: dict = {}
        self.notes: list[str] = []
        self.errors: list[dict] = []
        self.diagnostics: list[dict] = []
        self.requests = 0

    # ---------------------------------------------------------------- lifecycle
    def build_index(self) -> None:
        t0 = time.time()
        self.client = LspClient(self.cmd, self.root, self.verbose, self.log_path)
        self.client.initialize()
        self.client.wait_ready(self.timeout)
        self.stats = {"server": " ".join(self.cmd), "ready_seconds": round(time.time() - t0, 2), "tus": 0, "parsed": 0,
                      "cached": 0, "tu_errors": 0, "diagnostics": 0, "index_seconds": round(time.time() - t0, 2)}

    def provenance_inputs(self) -> dict[str, Optional[int]]:
        return dict(getattr(self, "_provenance_deps", {}))

    def close(self) -> None:
        if self.client:
            self.client.shutdown()
            self.client = None

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    def _req(self, method: str, params: Any, timeout: Optional[float] = None) -> Any:
        self.requests += 1
        t0 = time.monotonic()
        try:
            return self.client.request(method, params, timeout or min(self.timeout, 60))
        finally:
            self.stats["requests"] = self.requests
            counts = self.stats.setdefault("requests_by_method", {})
            counts[method] = counts.get(method, 0) + 1
            times = self.stats.setdefault("request_seconds", {})
            times[method] = round(times.get(method, 0) + time.monotonic() - t0, 6)

    def _open(self, path: str) -> str:
        uri = path_to_uri(path)
        if uri not in self.opened:
            if not hasattr(self, "_provenance_deps"):
                self._provenance_deps = {}
            self._provenance_deps[path] = os.stat(path).st_mtime_ns
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            self.client.notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": self.profile["language_id"],
                                                                         "version": 1, "text": text}})
            self.opened.add(uri)
            self.src_cache[uri] = text.splitlines()
        return uri

    def _lines(self, uri: str) -> list[str]:
        if uri not in self.src_cache:
            try:
                if not hasattr(self, "_provenance_deps"):
                    self._provenance_deps = {}
                self._provenance_deps[uri_to_path(uri)] = os.stat(uri_to_path(uri)).st_mtime_ns
                with open(uri_to_path(uri), encoding="utf-8", errors="replace") as fh:
                    self.src_cache[uri] = fh.read().splitlines()
            except OSError:
                self.src_cache[uri] = []
        return self.src_cache[uri]

    def _column(self, text: str, column: int, *, to_wire=False) -> int:
        encoding = getattr(self.client, "position_encoding", "utf-16")
        if encoding == "utf-32":
            return column
        codec, unit = ("utf-8", 1) if encoding == "utf-8" else ("utf-16-le", 2)
        if to_wire:
            return len(text[:column].encode(codec)) // unit
        return len(text.encode(codec)[:column * unit].decode(codec, errors="ignore"))

    def _text(self, uri: str, rng: dict) -> str:
        lines = self._lines(uri)
        s, e = rng["start"], rng["end"]
        if s["line"] >= len(lines):
            return ""
        s = {**s, "character": self._column(lines[s["line"]], s["character"])}
        e = {**e, "character": self._column(lines[e["line"]], e["character"]) if e["line"] < len(lines) else 0}
        if s["line"] == e["line"]:
            return lines[s["line"]][s["character"]:e["character"]]
        chunk = [lines[s["line"]][s["character"]:]] + lines[s["line"] + 1:e["line"]] + [lines[e["line"]][:e["character"]] if e["line"] < len(lines) else ""]
        return "\n".join(chunk)

    def _full_range(self, item: dict) -> dict:
        """The function's whole extent. rust-analyzer's call-hierarchy items carry it; pyright's `range` covers only
        the NAME, which would make the body hash a hash of the name. Prefer documentSymbol (full ranges), then a
        structural scan (indentation for Python, brace matching otherwise)."""
        rng = item["range"]
        sel = item.get("selectionRange") or rng
        uri = item["uri"]
        if self.lang == "rs":
            sym = self._symbol_at(uri, sel["start"], FUNC_KINDS)
            if sym and sym["name"] == item["name"]:
                return sym["range"]
        if item.get("kind") == 2:                 # a module caller (review finding H5): its extent is the whole file
            lines = self._lines(uri)
            return {"start": {"line": 0, "character": 0}, "end": {"line": max(len(lines) - 1, 0), "character": len(lines[-1]) if lines else 0}}
        if rng["end"]["line"] > rng["start"]["line"]:
            return rng
        for sym in self._symbols(uri):
            if sym["selectionRange"]["start"] == sel["start"] and sym["range"]["end"]["line"] > sym["range"]["start"]["line"]:
                return sym["range"]
        lines = self._lines(uri)
        start = rng["start"]["line"]
        if start >= len(lines):
            return rng
        if self.lang == "py":
            indent = len(lines[start]) - len(lines[start].lstrip())
            end = start
            for li in range(start + 1, len(lines)):
                if not lines[li].strip():
                    continue
                if len(lines[li]) - len(lines[li].lstrip()) <= indent:
                    break
                end = li
            return {"start": {"line": start, "character": 0}, "end": {"line": end, "character": len(lines[end])}}
        depth, seen = 0, False
        if self.lang == "rs":
            text = "\n".join(lines[start:])
            for tok in _ids.lex(text, "rs"):
                if tok.text == "{":
                    depth, seen = depth + 1, True
                elif tok.text == "}":
                    depth -= 1
                if seen and depth == 0:
                    end = start + text[:tok.end].count("\n")
                    return {"start": {"line": start, "character": 0},
                            "end": {"line": end, "character": self._column(lines[end], len(lines[end]), to_wire=True)}}
            return rng
        for li in range(start, len(lines)):
            for ch in lines[li]:
                if ch == "{":
                    depth, seen = depth + 1, True
                elif ch == "}":
                    depth -= 1
                if seen and depth == 0:
                    return {"start": {"line": start, "character": 0}, "end": {"line": li, "character": len(lines[li])}}
        return rng

    def _rel(self, uri: str) -> str:
        return _ids.rel(uri_to_path(uri), self.root)

    def _in_root(self, uri: str) -> bool:
        p = _ids.realpath(uri_to_path(uri))
        return os.path.commonpath([self.root, p]) == self.root and "/site-packages/" not in p and "/target/" not in p

    def _mkloc(self, uri: str, rng: dict) -> Loc:
        pos = rng["start"]
        lines = self._lines(uri)
        col = self._column(lines[pos["line"]], pos["character"]) if pos["line"] < len(lines) else pos["character"]
        return Loc(file=self._rel(uri), line=pos["line"] + 1, end_line=rng["end"]["line"] + 1, col=col + 1)

    # ---------------------------------------------------------------- symbols
    def _symbols(self, uri: str) -> list[dict]:
        """Flattened documentSymbol list: {name, kind, range, selectionRange, detail, path:[containers]}."""
        if uri in self.symbols_cache:
            return self.symbols_cache[uri]
        self._open(uri_to_path(uri))
        res = self._retry(lambda: self._req("textDocument/documentSymbol", {"textDocument": {"uri": uri}})) or []
        flat: list[dict] = []

        def walk(syms, path):
            for s in syms:
                if "location" in s:  # SymbolInformation (flat)
                    rng = s["location"]["range"]
                    flat.append({"name": s["name"], "kind": s["kind"], "range": rng, "selectionRange": rng, "detail": "", "path": list(path),
                                 "container": s.get("containerName")})
                else:
                    flat.append({"name": s["name"], "kind": s["kind"], "range": s["range"], "selectionRange": s.get("selectionRange", s["range"]),
                                 "detail": s.get("detail", ""), "path": list(path)})
                    kids = s.get("children") or []
                    if kids:
                        walk(kids, path + [(s["name"], s["kind"])])
        walk(res, [])
        self.symbols_cache[uri] = flat
        return flat

    @staticmethod
    def _contains(rng: dict, pos: dict) -> bool:
        s, e = rng["start"], rng["end"]
        return (s["line"], s["character"]) <= (pos["line"], pos["character"]) <= (e["line"], e["character"])

    def _symbol_at(self, uri: str, pos: dict, kinds: Optional[set] = None) -> Optional[dict]:
        best = None
        for s in self._symbols(uri):
            if kinds and s["kind"] not in kinds:
                continue
            if self._contains(s["range"], pos):
                if best is None or self._span(s["range"]) <= self._span(best["range"]):
                    best = s
        return best

    @staticmethod
    def _span(rng: dict) -> tuple[int, int]:
        return (rng["end"]["line"] - rng["start"]["line"], rng["end"]["character"] - rng["start"]["character"])

    def _retry(self, fn, tries: int = 40, sleep: float = 0.25):
        last = None
        for _ in range(tries):
            try:
                r = fn()
                return r
            except LspError as e:
                last = e
                if "no response" in str(e):
                    raise
                if not any(code in str(e) for code in ("-32801", "-32802", "-32800", "loading", "not loaded")):
                    raise
            time.sleep(sleep)
        if isinstance(last, LspError):
            raise last
        return last

    # ---------------------------------------------------------------- keys / ids
    @staticmethod
    def _key(item: dict) -> str:
        p = item["selectionRange"]["start"]
        return f"{item['uri']}#{p['line']}:{p['character']}|{item['name']}"

    def _scope_path(self, item: dict) -> list[tuple[str, int]]:
        """Containers of an item (classes, modules, enclosing functions), in this order of evidence: the documentSymbol
        path of the function symbol at the item's position; else the class named in the item's `detail`
        (`class X (file)`: Pyright lists only the last `@overload` of a name as a symbol, so earlier overloads match no
        function symbol); else the nearest container symbol enclosing the position."""
        uri = item["uri"]
        pos = item["selectionRange"]["start"]
        sym = self._symbol_at(uri, pos, FUNC_KINDS)
        if sym is not None:
            return list(sym["path"])
        m = re.match(r"^class (\S+) \(", item.get("detail") or "")
        if m:
            return [(m.group(1), 5)]
        cont = self._symbol_at(uri, pos, CONTAINER_KINDS)
        return (list(cont["path"]) + [(cont["name"], cont["kind"])]) if cont else []

    def _qualname(self, item: dict) -> str:
        parts = []
        for name, kind in self._scope_path(item):
            if kind in CONTAINER_KINDS:
                if self.lang == "rs" and name.startswith("impl"):
                    from ..rustsyntax import impl_name
                    parts.append(impl_name(name))
                    continue
                n = re.sub(r"^impl\s+(?:<[^>]*>\s*)?(?:.*\bfor\s+)?", "", name).strip()
                n = re.sub(r"<.*>$", "", n)
                parts.append(n)
        parts.append(item["name"])
        return self.sep.join(parts)

    def _register(self, item: dict) -> str:
        source_sym = None
        if self.lang == "rs" and urlparse(item["uri"]).scheme == "file" and item.get("kind") in FUNC_KINDS:
            source_sym = self._symbol_at(item["uri"], item["selectionRange"]["start"], FUNC_KINDS)
            if source_sym and source_sym["name"] == item["name"]:
                # Incoming hierarchy items for attribute macros can select the
                # attribute instead of the function name. Canonical source
                # ranges keep hover requests and body hashes independent of order.
                item = {**item, "range": source_sym["range"], "selectionRange": source_sym["selectionRange"]}
        key = self._key(item)
        if key not in self.items:
            self.items[key] = item
            if urlparse(item["uri"]).scheme != "file":
                self.ids[key] = None   # no source identity can be established; keep a reasoned ghost
                self._source_less.add(key)
                return key
            if self.lang == "rs" and item.get("kind") in FUNC_KINDS:
                sym = source_sym
                if sym is None or sym["name"] != item["name"]:
                    typ = self._symbol_at(item["uri"], item["selectionRange"]["start"], TYPE_KINDS | {22})
                    if typ and typ["name"] == item["name"]:
                        self._nonfunctions.add(key)
                    else:
                        self.ids[key] = None
                        self._source_less.add(key)
                        return key
            cand = _ids.node_id(self.lang, self._rel(item["uri"]), self._qualname(item))
            if cand in self._used_ids:
                if self.lang == "rs":
                    self.items.pop(key, None)
                    raise FrontendError(f"ambiguous Rust source identity {cand}; refusing a position-based ID")
                cand = f"{cand}#{_ids.short_hash(key)}"      # residual collision only; position-dependent by design
            self.ids[key] = cand
            self._used_ids.add(cand)
        return key

    # ---------------------------------------------------------------- Frontend API
    def locate_entry(self, file: str, symbol: str) -> str:
        path = os.path.abspath(file if os.path.isabs(file) else os.path.join(self.root, file))
        if not os.path.exists(path):
            raise EntryNotFound(f"file not found: {file}")
        uri = self._open(path)
        syms = [s for s in self._symbols(uri) if s["kind"] in FUNC_KINDS]
        want = symbol.replace("::", self.sep).replace(".", self.sep)
        def matches(s):
            qual = self._qualname({"uri": uri, "name": s["name"], "selectionRange": s["selectionRange"]})
            return s["name"] == symbol or qual == want or qual.endswith(self.sep + want)
        hits = [s for s in syms if matches(s)]
        if not hits:
            import difflib
            names = sorted({s["name"] for s in syms})
            raise EntryNotFound(f"function '{symbol}' not found in {file} (server: {self.cmd[0]})", difflib.get_close_matches(symbol, names, n=5, cutoff=0.5))
        if len(hits) > 1:
            candidates = [self._qualname({"uri": uri, "name": s["name"], "selectionRange": s["selectionRange"]}) for s in hits]
            raise EntryNotFound(f"ambiguous function {symbol!r} in {file}; qualify the entry", candidates)
        s = hits[0]
        items = self._retry(lambda: self._req("textDocument/prepareCallHierarchy", {"textDocument": {"uri": uri}, "position": s["selectionRange"]["start"]}))
        if not items:
            raise FrontendError(f"{self.cmd[0]} returned no call-hierarchy item for {symbol}; is the project loaded (Cargo.toml / pyrightconfig.json at {self.root})?")
        return self._register(items[0])

    def stable_id(self, key: str) -> Optional[str]:
        return self.ids.get(key)

    def _hover_sig(self, item: dict) -> tuple[str, Optional[str]]:
        """(signature text, module path block) from hover at the item's name."""
        uri = item["uri"]
        self._open(uri_to_path(uri))
        try:
            hov = self._req("textDocument/hover", {"textDocument": {"uri": uri}, "position": item["selectionRange"]["start"]})
        except LspError:
            hov = None
        blocks = _code_blocks(hov)
        pattern = (r"\bfn\s+" + re.escape(item["name"]) + r"\b") if self.lang == "rs" else r"\b(fn|def|func)\b"
        sig = next((b for b in blocks if re.search(pattern, b)), None)
        path_block = next((b for b in blocks if b is not sig and re.match(r"^[\w:.]+$", b.strip())), None)
        if sig is None:
            sig = item.get("detail") or self._text(uri, {"start": item["range"]["start"], "end": item["selectionRange"]["end"]}).strip() + "(...)"
            if self.lang == "rs":
                from ..rustsyntax import source_signature
                sig = source_signature(self._text(uri, self._full_range(item)), item["name"]) or sig
        return _ids.squash_ws(sig, self.lang), path_block

    def _param_positions(self, item: dict, params: list[dict]) -> dict[str, dict]:
        """Position of each parameter name inside the function header (for typeDefinition)."""
        uri = item["uri"]
        lines = self._lines(uri)
        start = item["range"]["start"]["line"]
        end = min(item["range"]["end"]["line"], start + 60)
        header_end = end
        for li in range(start, end + 1):
            if li >= len(lines):
                break
            if (self.lang == "rs" and "{" in lines[li]) or (self.lang == "py" and lines[li].rstrip().endswith(":")) or (self.lang not in ("rs", "py") and "{" in lines[li]):
                header_end = li
                break
        out: dict[str, dict] = {}
        for p in params:
            name = p["name"]
            if name in ("self", "cls"):
                continue
            pat = re.compile(r"(?<![\w.])" + re.escape(name) + r"\s*:")
            for li in range(start, header_end + 1):
                if li >= len(lines):
                    break
                m = pat.search(lines[li])
                if m:
                    out[name] = {"line": li, "character": self._column(lines[li], m.start(), to_wire=True)}
                    break
        return out

    def _type_at(self, uri: str, pos: dict, spelled: Optional[str] = None) -> Optional[str]:
        """Resolve the type of the symbol at pos via typeDefinition; record and return a type key.
        When `spelled` is given, the resolved type's name must occur in it (guards against servers that
        jump into a type alias, e.g. a `fn(&Desc)` alias resolving to `Desc`)."""
        try:
            res = self._req("textDocument/typeDefinition", {"textDocument": {"uri": uri}, "position": pos}, timeout=20)
        except LspError:
            return None
        loc = res[0] if isinstance(res, list) and res else (res if isinstance(res, dict) else None)
        if not loc:
            return None
        turi = loc.get("targetUri") or loc.get("uri")
        trng = loc.get("targetSelectionRange") or loc.get("targetRange") or loc.get("range")
        if not turi or not trng:
            return None
        key = self._record_type(turi, trng["start"])
        if key and spelled is not None:
            tname = self.types[key]["name"]
            if not re.search(r"(?<![\w])" + re.escape(tname) + r"(?![\w])", spelled):
                return None
        return key

    def _record_type(self, uri: str, pos: dict) -> Optional[str]:
        key = f"{uri}#{pos['line']}:{pos['character']}"
        if key in self.types:
            return key
        system = not self._in_root(uri)
        sym = None
        if not system or True:
            try:
                sym = self._symbol_at(uri, pos, TYPE_KINDS | {19})
            except LspError:
                sym = None
        if sym is None:
            return None
        key2 = f"{uri}#{sym['selectionRange']['start']['line']}:{sym['selectionRange']['start']['character']}"
        if key2 in self.types:
            self.types[key] = self.types[key2]
            self.type_ids[key] = self.type_ids[key2]
            return key2
        kind = {5: "class", 23: "struct", 10: "enum", 11: "interface", 26: "typedef", 19: "object"}.get(sym["kind"], "type")
        qual = self.sep.join([n for n, k in sym["path"] if k in CONTAINER_KINDS and k != 19] + [sym["name"]])
        entry = {"kind": kind, "name": sym["name"], "qualname": qual, "uri": uri, "range": sym["range"], "system": system,
                 "fields": [], "enumerators": [], "field_positions": [], "detail": sym.get("detail", "")}
        self.types[key2] = entry
        self.types[key] = entry
        tid = _ids.type_id(self.lang, self._rel(uri), kind, qual)
        self.type_ids[key2] = tid
        self.type_ids[key] = tid
        if system:
            return key2  # stub only
        children = [s for s in self._symbols(uri) if s["path"] and s["path"][-1][0] == sym["name"] and len(s["path"]) == len(sym["path"]) + 1 and s["kind"] in FIELD_KINDS]
        for i, ch in enumerate(children[:64]):
            if ch["kind"] == 22:
                entry["enumerators"].append({"name": ch["name"], "value": i})
                continue
            ftype = ch.get("detail") or ""
            if not ftype:
                line = self._lines(uri)[ch["selectionRange"]["start"]["line"]] if ch["selectionRange"]["start"]["line"] < len(self._lines(uri)) else ""
                am = re.match(r"^\s*" + re.escape(ch["name"]) + r"\s*:\s*(.+?)\s*(?:=.*)?$", line)
                if am:
                    ftype = am.group(1).strip()
            if not ftype:
                try:
                    hov = self._req("textDocument/hover", {"textDocument": {"uri": uri}, "position": ch["selectionRange"]["start"]}, timeout=20)
                    blk = _code_blocks(hov)
                    if blk:
                        mm = re.search(r":\s*(.+?)(?:\s*=.*)?$", blk[0].splitlines()[0])
                        ftype = mm.group(1).strip() if mm else blk[0].splitlines()[0]
                except LspError:
                    ftype = ""
            entry["fields"].append({"name": ch["name"], "type": ftype or "?", "pos": ch["selectionRange"]["start"]})
        return key2

    # ---------------------------------------------------------------- function records
    @staticmethod
    def _copy_record(rec: FunctionRecord) -> FunctionRecord:
        """Traversal mutates `depth` and `calls` on the node it is handed (and may append to call-site lists), so a
        memoised record is never shared: every caller gets its own copy (review finding H4 safeguard)."""
        return FunctionRecord(node=copy.deepcopy(rec.node), callsites=[copy.copy(cs) for cs in rec.callsites],
                              type_keys=list(rec.type_keys), global_keys=list(rec.global_keys))

    @staticmethod
    def _is_method(item: dict) -> bool:
        """Pyright reports methods as kind 12 (Function) in call-hierarchy items; the class then shows only in `detail`."""
        return item.get("kind") in (6, 9) or bool(re.match(r"^class \S+ \(", item.get("detail") or ""))

    @staticmethod
    def _pos(item: dict) -> tuple[int, int]:
        p = item["selectionRange"]["start"]
        return (p["line"], p["character"])

    def _is_overload(self, item: dict) -> bool:
        """True when an `@overload` / `@typing.overload` decorator sits above the declaration (blank, comment and other
        decorator lines are skipped)."""
        lines = self._lines(item["uri"])
        li = item["range"]["start"]["line"] - 1
        while li >= 0:
            s = lines[li].strip() if li < len(lines) else ""
            if not s or s.startswith("#"):
                li -= 1
                continue
            if s.startswith("@"):
                if re.match(r"^@(?:typing\.)?overload\b", s):
                    return True
                li -= 1
                continue
            return False
        return False

    def _scope_label(self, item: dict) -> Optional[str]:
        """Lexical scope of an item: its container path (`str`), the CONFIRMED module scope `<module>` (a plain-function
        `detail` such as `(builtins.pyi)`, or documentSymbol succeeded and no container holds the position), or None
        when the scope is unknown — an unknown scope never joins a family."""
        containers = [n for n, k in self._scope_path(item) if k in CONTAINER_KINDS]
        if containers:
            return ".".join(containers)
        if re.match(r"^\(.+\)", item.get("detail") or "") or self._symbols(item["uri"]):
            return "<module>"
        return None

    def _family_key(self, item: dict) -> Optional[tuple]:
        """(uri, scope, name) of a VERIFIED Python stub overload family member, else None: the item must come from a
        `.pyi` or a library file, carry `@overload`, and have a known lexical scope. Never a name-only rule; Rust and
        other servers are untouched."""
        if self.lang != "py":
            return None
        uri = item["uri"]
        if not (uri.endswith(".pyi") or not self._in_root(uri)):
            return None
        if not self._is_overload(item):
            return None
        scope = self._scope_label(item)
        if scope is None:
            return None
        return (uri, scope, item["name"])

    def _outgoing(self, item: dict, uri: str) -> list[CallSite]:
        """Call sites of an item. The members of a verified stub overload family (Pyright returns one call-hierarchy
        item per `@overload`) collapse into ONE target — the member at the smallest position — with one call site per
        distinct fromRange; the representative's `family` metadata is kept for `declaration()` so the migration mapper
        has independent evidence. Everything else is one target per item."""
        callsites: list[CallSite] = []
        try:
            calls = self._req("callHierarchy/outgoingCalls", {"item": item}) or []
        except LspError as e:
            self.errors.append({"file": self._rel(uri), "error": str(e)})
            calls = []
        families: dict[tuple, dict] = {}
        order: list[tuple] = []
        for c in calls:
            to = c["to"]
            fk = self._family_key(to)
            if fk is None:
                ckey = self._register(to)
                for fr in c.get("fromRanges") or [None]:
                    callsites.append(CallSite(callee_key=ckey, name=to["name"], loc=self._mkloc(uri, fr) if fr else None, kind="call",
                                              args=self._call_args(uri, fr) if fr else []))
                continue
            fam = families.get(fk)
            if fam is None:
                fam = families[fk] = {"item": to, "ranges": [], "size": 0}
                order.append(fk)
            fam["size"] += 1
            if self._pos(to) < self._pos(fam["item"]):
                fam["item"] = to
            fam["ranges"].extend(c.get("fromRanges") or [])
        for fk in order:
            fam = families[fk]
            rep = fam["item"]
            ckey = self._register(rep)
            self._families[ckey] = {"size": fam["size"], "evidence": "@overload", "scope": fk[1]}
            seen: set[tuple[int, int]] = set()
            ranges = []
            for fr in fam["ranges"]:
                k = (fr["start"]["line"], fr["start"]["character"])
                if k not in seen:
                    seen.add(k)
                    ranges.append(fr)
            for fr in ranges or [None]:
                callsites.append(CallSite(callee_key=ckey, name=rep["name"], loc=self._mkloc(uri, fr) if fr else None, kind="call",
                                          args=self._call_args(uri, fr) if fr else []))
        return callsites

    def _module_record(self, key: str, item: dict) -> FunctionRecord:
        """A module caller (Pyright's `(module) x.py`, kind 2, zero-length range): a `module` node spanning the whole
        file whose body hash covers the whole source (review finding H5). Outgoing calls are skipped for Python only:
        every one of the 12,638 module outgoing requests in the recorded evidence returned nothing."""
        uri = item["uri"]
        lines = self._lines(uri)
        full = self._full_range(item)
        base = os.path.basename(uri_to_path(uri))
        node = Node(id=self.ids[key], kind="module", name=item["name"], qualname=item["name"], lang=self.lang,
                    loc=self._mkloc(uri, full), signature=f"module {base}", storage=None,
                    body_hash=_ids.body_hash("\n".join(lines), self.lang), precision="lsp",
                    returns=None, params=[], globals=GlobalRefs(), attrs={})
        callsites = [] if self.lang == "py" else self._outgoing(item, uri)
        return FunctionRecord(node=node, callsites=callsites, type_keys=[], global_keys=[])

    def caller_function(self, key: str) -> Optional[FunctionRecord]:
        """Caller-side traversal does not consume unrelated outgoing call sites."""
        return self.function(key, with_calls=False)

    def function(self, key: str, *, with_calls=True) -> Optional[FunctionRecord]:
        cached = self._fn_cache.get(key)
        if cached is not None:
            return self._copy_record(cached)
        cached = self._caller_cache.get(key)
        if cached is not None:
            rec = self._copy_record(cached)
            if with_calls:
                rec.callsites = self._outgoing(self.items[key], self.items[key]["uri"])
                self._fn_cache[key] = rec
            return self._copy_record(rec)
        item = self.items.get(key)
        if item is None:
            return None
        uri = item["uri"]
        if not self._in_root(uri):
            return None
        if item.get("kind") == 2:
            rec = self._module_record(key, item)
            self._fn_cache[key] = rec
            return self._copy_record(rec)
        sig, path_block = self._hover_sig(item)
        params, ret = parse_signature(sig, self.lang)
        full = self._full_range(item)
        positions = self._param_positions({**item, "range": full}, params)
        type_keys: list[str] = []
        pparams: list[Param] = []
        for p in params:
            tk = None
            pos = positions.get(p["name"])
            if pos and not _PRIMITIVE.match(p["type"]):
                tk = self._type_at(uri, pos, p["type"])
            if tk:
                type_keys.append(tk)
            pparams.append(Param(name=p["name"], type=p["type"], type_ref=self.type_ids.get(tk or ""), dir=p["dir"],
                                 dir_source="heuristic" if self.lang == "rs" else "explicit"))
        qual = self._qualname(item)
        body = self._text(uri, full)
        node = Node(id=self.ids[key], kind="method" if self._is_method(item) else "function", name=item["name"], qualname=qual,
                    lang=self.lang, loc=self._mkloc(uri, full), signature=sig, storage=None,
                    body_hash=_ids.body_hash(body, self.lang), precision="lsp",
                    returns=TypeUse(type=ret) if ret else None, params=pparams, globals=GlobalRefs(),
                    attrs={"module": path_block} if path_block else {})
        rec = FunctionRecord(node=node, callsites=self._outgoing(item, uri) if with_calls else [], type_keys=_uniq(type_keys), global_keys=[])
        if with_calls:
            self._fn_cache[key] = rec
        else:
            self._caller_cache[key] = rec
        return self._copy_record(rec)

    def _call_args(self, uri: str, rng: dict) -> list[str]:
        """Spelled arguments of the call whose callee name ends at `rng.end`: skip the callee tail (turbofish,
        generics, Rust `!`) to the `(`, then let `ids.paren_args` match the list and split it — literal-aware,
        so commas, brackets and `>` inside strings never split (review finding H1)."""
        lines = self._lines(uri)
        li = rng["end"]["line"]
        if li >= len(lines):
            return []
        ci = self._column(lines[li], rng["end"]["character"])
        if self.lang == "rs":
            import bisect
            cache = getattr(self, "_rs_call_tokens", None)
            if cache is None:
                cache = self._rs_call_tokens = {}
            if uri not in cache:
                text = "\n".join(lines)
                toks = _ids.lex(text, "rs")
                offsets, total = [], 0
                for line in lines:
                    offsets.append(total)
                    total += len(line) + 1
                cache[uri] = text, toks, [t.start for t in toks], offsets
            text, toks, starts, offsets = cache[uri]
            first = bisect.bisect_left(starts, offsets[li] + ci)
            angles = 0
            for i in range(first, len(toks)):
                t = toks[i]
                if t.text == "<":
                    angles += 1
                elif t.text in (">", ">>"):
                    angles = max(0, angles - len(t.text))
                elif t.text == "(" and not angles:
                    depth = 0
                    for end in toks[i:]:
                        depth += 1 if end.text in ("(", "[", "{") else (-1 if end.text in (")", "]", "}") else 0)
                        if depth == 0:
                            return _ids.paren_args(text[t.start:end.end], "rs")
                    return []
                elif not angles and t.text in (";", "{", "}", "=", ",", ".", "?"):
                    return []
            return []
        last = len(lines)
        while li < last:
            line = lines[li]
            while ci < len(line):
                ch = line[ci]
                if ch == "(":
                    return _ids.paren_args("\n".join([line[ci:]] + lines[li + 1:last]), self.lang)
                if ch in " \t" or (ch == ":" and self.lang == "rs") or ch == "!" or ch.isalnum() or ch == "_" or ch in "<>:":
                    ci += 1          # turbofish / generic args before '('
                    continue
                return []
            li, ci = li + 1, 0
        return []

    def declaration(self, key: str) -> Optional[DeclRecord]:
        item = self.items.get(key)
        if item is None:
            return None
        if key in self._source_less:
            return DeclRecord(id=None, name=item["name"], loc=None, has_definition=False, system=True, relpath=None,
                              reason="language server target has no matching source declaration (macro/generated target)")
        if key in self._nonfunctions:
            return DeclRecord(id=self.ids[key], name=item["name"], loc=self._mkloc(item["uri"], item["range"]),
                              has_definition=False, system=not self._in_root(item["uri"]), relpath=self._rel(item["uri"]),
                              reason="not a function (constructor/variant)")
        uri = item["uri"]
        inside = self._in_root(uri)
        fam = self._families.get(key)
        if item.get("kind") == 2:                 # module caller: admissible like a function, spanning the file (H5)
            loc = self._mkloc(uri, self._full_range(item))
            return DeclRecord(id=self.ids[key], name=item["name"], loc=loc, has_definition=inside, system=not inside, relpath=loc.file,
                              reason=None if inside else "outside project root (library)")
        loc = self._mkloc(uri, item["range"])
        if item.get("kind") not in FUNC_KINDS:
            return DeclRecord(id=self.ids[key], name=item["name"], loc=loc, has_definition=False, system=not inside, relpath=loc.file,
                              reason=f"not a function ({SK.get(item.get('kind'), 'symbol')} constructor/variant)", family=fam)
        if inside and uri.endswith(".pyi"):      # a project stub: declared here, defined nowhere (library stubs keep their wording)
            return DeclRecord(id=self.ids[key], name=item["name"], loc=loc, has_definition=False, system=False, relpath=loc.file,
                              reason="stub declaration (a .pyi has no body)", family=fam)
        return DeclRecord(id=self.ids[key], name=item["name"], loc=loc, has_definition=inside, system=not inside, relpath=loc.file,
                          reason=None if inside else "outside project root (library)", family=fam)

    def type(self, key: str) -> Optional[TypeRecord]:
        t = self.types.get(key)
        if t is None:
            return None
        nested: list[str] = []
        fields: list[Field] = []
        for f in t["fields"]:
            fk = f.get("type_key")
            if fk is None and not t["system"] and not _PRIMITIVE.match(f["type"]):
                fk = self._type_at(t["uri"], f["pos"], f["type"])
                f["type_key"] = fk or ""
            if fk:
                nested.append(fk)
            fields.append(Field(name=f["name"], type=f["type"], type_ref=self.type_ids.get(fk or "")))
        td = TypeDef(id=self.type_ids[key], kind=t["kind"], name=t["qualname"] or t["name"], lang=self.lang,
                     loc=self._mkloc(t["uri"], t["range"]), size=None, align=None, fields=fields,
                     enumerators=[Enumerator(name=e["name"], value=e["value"]) for e in t["enumerators"]],
                     underlying=t.get("detail") or None, system=t["system"])
        return TypeRecord(typedef=td, nested_keys=_uniq(nested), alias_keys=[])

    def global_var(self, key: str) -> Optional[GlobalVar]:
        return None

    def callers(self, key: str) -> list[tuple[str, CallSite]]:
        item = self.items.get(key)
        if item is None:
            return []
        try:
            calls = self._req("callHierarchy/incomingCalls", {"item": item}, timeout=self.timeout if self.lang == "rs" else None) or []
        except LspError as exc:
            self.errors.append({"file": self._rel(item["uri"]), "error": str(exc)})
            if self.lang == "rs":
                raise
            return []
        out = []
        for c in calls:
            frm = c["from"]
            fkey = self._register(frm)
            for fr in c.get("fromRanges") or [None]:
                out.append((fkey, CallSite(callee_key=key, name=item["name"], loc=self._mkloc(frm["uri"], fr) if fr else None,
                                           kind="call", args=self._call_args(frm["uri"], fr) if fr else [])))
        return out


def _uniq(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
