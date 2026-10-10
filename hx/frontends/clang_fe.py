"""C/C++ frontend built on libclang.

Pipeline:
  compile_commands.json
    -> one parse job per translation unit (TU), args sanitized for libclang
    -> per-TU JSON summary (parsed in parallel, cached by file mtimes)
    -> merged index keyed by USR (libclang's cross-TU symbol identity)
    -> Frontend API consumed by hx.traverse

Everything the workers return is plain JSON so it can be cached and crossed
between processes; libclang objects never leave the worker.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Optional

from .. import ids as _ids
from ..cache import TUCache

# Bump whenever the per-TU summary format or the hashing/ID rules change: it is part of the cache key,
# so stale .hx/cache entries from an older hx can never be mixed with fresh ones.
SUMMARY_VERSION = 2
from ..model import Loc, Node, Param, TypeUse, GlobalRefs, TypeDef, Field, Enumerator, GlobalVar
from .base import Frontend, FunctionRecord, DeclRecord, TypeRecord, CallSite, EntryNotFound, FrontendError

CPP_EXT = {".cpp", ".cc", ".cxx", ".C", ".c++", ".hpp", ".hh", ".hxx", ".ipp", ".mm"}
SYSTEM_PREFIXES = ("/usr/include", "/usr/lib", "/usr/local/include", "/opt/")

_ANON_RE = re.compile(r"\((?:unnamed|anonymous)(?: (struct|union|enum|class))?(?: at [^)]*)?\)")
_ANON_QUAL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_:]*::(?=\(anonymous)")
_WS_RE = re.compile(r"\s+")


def _configure_cindex():
    from clang import cindex  # deferred: `hx` must import without libclang present
    lib = os.environ.get("HX_LIBCLANG")
    if lib and not cindex.Config.loaded:
        cindex.Config.set_library_file(lib)
    return cindex


def _anon_sub(m: "re.Match[str]") -> str:
    return f"(anonymous {m.group(1)})" if m.group(1) else "(anonymous)"


def clean_spelling(s: str) -> str:
    s = _ANON_RE.sub(_anon_sub, s)
    s = _ANON_QUAL_RE.sub("", s)
    return _WS_RE.sub(" ", s).strip()


def member_name(spelling: str) -> str:
    """Field name; '' for C11 anonymous struct/union members (libclang spells those as 'T::(anonymous at ...)')."""
    if not spelling or "(anonymous" in spelling or "(unnamed" in spelling:
        return ""
    return spelling


# ============================================================ compile commands

@dataclass
class TUJob:
    file: str
    directory: str
    args: list[str]
    lang: str
    compiler: str


_DROP_FLAGS = {
    "-c", "-S", "-E", "-M", "-MM", "-MD", "-MMD", "-MP", "-MG", "-pipe",
    "-fno-var-tracking-assignments", "-fconserve-stack", "-fno-allow-store-data-races",
    "-mno-fp-ret-in-387", "-fstack-usage", "-fuse-linker-plugin", "-static-libgcc",
    "-fno-sync-libcalls", "-fdiagnostics-show-option", "-save-temps",
}
_DROP_WITH_VALUE = {"-o", "-MF", "-MT", "-MQ", "-MJ", "--param", "-dumpbase", "-dumpdir", "-auxbase"}
_DROP_PREFIXES = ("-Wa,", "-Wl,", "-Wp,", "-fdiagnostics-color", "-fplugin=", "-specs=", "-fdump-",
                  "-fprofile-", "-fcf-protection", "-mindirect-branch", "-mfunction-return",
                  "-fsanitize-coverage", "--coverage", "-fno-reorder-blocks-and-partition",
                  "-fipa-", "-fno-ipa-", "-ftree-", "-fno-tree-", "-fmerge-constants", "-fno-merge-constants",
                  "-flto", "-fno-fat-lto-objects", "-dumpbase", "-dumpdir", "-auxbase-strip")
_PATH_FLAGS = ("-I", "-isystem", "-iquote", "-idirafter", "-include", "-imacros", "-isysroot", "-F", "-iprefix",
               "-iwithprefix", "-iwithprefixbefore", "-cxx-isystem", "-c-isystem")
_TRIPLE_RE = re.compile(r"^(?P<triple>[A-Za-z0-9_]+(?:-[A-Za-z0-9_.]+){1,3})-(?P<tool>gcc|g\+\+|cc|c\+\+|clang|clang\+\+)(?:-[0-9.]+)?$")


def _abs(p: str, directory: str) -> str:
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(directory, p))


def sanitize_args(raw: list[str], directory: str, source: str) -> list[str]:
    """Strip compiler/output/dep flags, absolutize include paths, drop gcc-only options."""
    out: list[str] = []
    args = list(raw)
    src_abs = os.path.abspath(_abs(source, directory))
    i = 0
    while i < len(args):
        a = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else None
        if a in _DROP_WITH_VALUE:
            i += 2
            continue
        if a in _DROP_FLAGS or a.startswith(_DROP_PREFIXES):
            i += 1
            continue
        if a.startswith("-o") and len(a) > 2 and not a.startswith("-objc"):
            i += 1
            continue
        if a == "--sysroot" and nxt is not None:
            out += ["--sysroot=" + _abs(nxt, directory)]
            i += 2
            continue
        if a.startswith("--sysroot="):
            out.append("--sysroot=" + _abs(a.split("=", 1)[1], directory))
            i += 1
            continue
        hit = False
        for pf in sorted(_PATH_FLAGS, key=len, reverse=True):
            if a == pf and nxt is not None:
                out += [pf, _abs(nxt, directory)]
                i += 2
                hit = True
                break
            if a.startswith(pf) and len(a) > len(pf) and pf in ("-I", "-F", "-isystem", "-iquote", "-idirafter", "-include", "-imacros"):
                out.append(pf + _abs(a[len(pf):], directory))
                i += 1
                hit = True
                break
        if hit:
            continue
        if not a.startswith("-"):
            cand = os.path.abspath(_abs(a, directory))
            if cand == src_abs or os.path.basename(a) == os.path.basename(source) and a.endswith(os.path.basename(source)):
                i += 1
                continue
            # positional non-source (rare); keep
        out.append(a)
        i += 1
    return out


def detect_lang(args: list[str], source: str, compiler: str) -> str:
    for i, a in enumerate(args):
        if a == "-x" and i + 1 < len(args):
            return "cpp" if "++" in args[i + 1] else "c"
        if a.startswith("-x") and len(a) > 2:
            return "cpp" if "++" in a[2:] else "c"
    ext = os.path.splitext(source)[1]
    if ext in CPP_EXT:
        return "cpp"
    base = os.path.basename(compiler)
    if any(t in base for t in ("g++", "clang++", "c++")):
        return "cpp"
    return "c"


_cross_cache: dict[tuple[str, str], list[str]] = {}


def cross_compiler_args(compiler: str, lang: str) -> list[str]:
    """For `arm-none-eabi-gcc`-style compilers: --target plus the compiler's own system include dirs."""
    base = os.path.basename(compiler)
    m = _TRIPLE_RE.match(base)
    if not m:
        return []
    key = (compiler, lang)
    if key in _cross_cache:
        return _cross_cache[key]
    triple = m.group("triple")
    extra = [f"--target={triple}"]
    exe = shutil.which(compiler)
    if exe and "clang" not in m.group("tool"):
        try:
            r = subprocess.run([exe, "-E", "-v", "-x", "c++" if lang == "cpp" else "c", "-"],
                               input="", capture_output=True, text=True, timeout=20)
            inside = False
            for line in r.stderr.splitlines():
                if line.startswith("#include <...> search starts here"):
                    inside = True
                    continue
                if line.startswith("End of search list"):
                    break
                if inside and line.strip():
                    extra += ["-isystem", os.path.normpath(line.strip())]
        except (OSError, subprocess.SubprocessError):
            pass
    _cross_cache[key] = extra
    return extra


def detect_resource_dir(explicit: Optional[str] = None) -> Optional[str]:
    """Clang resource dir (stddef.h, stdint.h ...). The pip libclang wheel ships none, so borrow the system one."""
    if explicit:
        return explicit
    env = os.environ.get("HX_RESOURCE_DIR")
    if env:
        return env
    for exe in ("clang", "clang-20", "clang-19", "clang-18", "clang-17", "clang-16", "clang-15", "clang-14"):
        path = shutil.which(exe)
        if not path:
            continue
        try:
            r = subprocess.run([path, "-print-resource-dir"], capture_output=True, text=True, timeout=10)
            rd = r.stdout.strip()
            if r.returncode == 0 and rd and os.path.isdir(os.path.join(rd, "include")):
                return rd
        except (OSError, subprocess.SubprocessError):
            continue
    cands = glob.glob("/usr/lib/llvm-*/lib/clang/*") + glob.glob("/usr/lib/clang/*") + glob.glob("/usr/local/lib/clang/*")
    cands = [c for c in cands if os.path.isdir(os.path.join(c, "include"))]

    def ver(c):
        try:
            return tuple(int(x) for x in os.path.basename(c).split("."))
        except ValueError:
            return (0,)
    return max(cands, key=ver) if cands else None


def find_compile_commands(root: str, explicit: Optional[str] = None) -> str:
    if explicit:
        p = os.path.abspath(explicit)
        if os.path.isdir(p):
            if os.path.exists(os.path.join(p, "compile_commands.json")):
                return p
            raise FrontendError(f"no compile_commands.json in {p}")
        if os.path.isfile(p):
            return os.path.dirname(p)
        raise FrontendError(f"--compile-commands path not found: {explicit}")
    cands = [os.path.join(root, "compile_commands.json"),
             os.path.join(root, "build", "compile_commands.json"),
             os.path.join(root, "out", "compile_commands.json")]
    cands += sorted(glob.glob(os.path.join(root, "*", "compile_commands.json")))
    cands += sorted(glob.glob(os.path.join(root, "*", "*", "compile_commands.json")))
    for c in cands:
        if os.path.isfile(c):
            return os.path.dirname(os.path.abspath(c))
    raise FrontendError(
        "compile_commands.json not found under %s. Generate it with "
        "`cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON ...` or `bear -- make`, or pass --compile-commands." % root)


def load_jobs(cc_dir: str, extra_args: list[str], resource_dir: Optional[str]) -> list[TUJob]:
    cindex = _configure_cindex()
    try:
        db = cindex.CompilationDatabase.fromDirectory(cc_dir)
    except cindex.CompilationDatabaseError as e:
        raise FrontendError(f"cannot load compilation database from {cc_dir}: {e}")
    jobs: dict[str, TUJob] = {}
    for cmd in db.getAllCompileCommands():
        raw = list(cmd.arguments)
        if not raw:
            continue
        compiler, rest = raw[0], raw[1:]
        directory = cmd.directory
        source = cmd.filename
        src_abs = os.path.abspath(_abs(source, directory))
        if src_abs in jobs:
            continue  # same file compiled twice (multi-config); first wins
        args = sanitize_args(rest, directory, source)
        lang = detect_lang(args, source, compiler)
        if not any(a == "-x" or a.startswith("-x") for a in args):
            args = ["-x", "c++" if lang == "cpp" else "c"] + args
        args += cross_compiler_args(compiler, lang)
        if resource_dir and not any(a.startswith("-resource-dir") for a in args):
            args = ["-resource-dir", resource_dir] + args
        args += list(extra_args)
        jobs[src_abs] = TUJob(file=src_abs, directory=directory, args=args, lang=lang, compiler=compiler)
    if not jobs:
        raise FrontendError(f"compilation database at {cc_dir} has no entries")
    return list(jobs.values())


# ============================================================ worker: one TU -> summary

def parse_tu(job: dict) -> dict:
    """Process-pool entry point. Returns a JSON-able summary (or {'error': ...})."""
    try:
        cindex = _configure_cindex()
        idx = cindex.Index.create()
        opts = cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
        args = job["args"]
        retried = False
        try:
            tu = idx.parse(job["file"], args=args, options=opts)
        except cindex.TranslationUnitLoadError:
            keep = ("-I", "-D", "-U", "-std", "-isystem", "-iquote", "-idirafter", "-include", "-imacros",
                    "-resource-dir", "--target", "--sysroot", "-x", "-nostdinc", "-fno-builtin", "-fms-extensions")
            stripped, skip = [], False
            for a in args:
                if skip:
                    stripped.append(a)
                    skip = False
                    continue
                if a.startswith(("-f", "-m", "-W", "-O", "-g")) and not a.startswith(keep):
                    continue
                stripped.append(a)
                if a in ("-I", "-D", "-U", "-isystem", "-iquote", "-idirafter", "-include", "-imacros", "-resource-dir", "-x"):
                    skip = True
            tu = idx.parse(job["file"], args=stripped, options=opts)
            retried = True
        out = _TUExtractor(tu, job).run()
        out["retried_stripped"] = retried
        return out
    except Exception as e:  # noqa: BLE001 - surfaced to the user per TU
        return {"file": job["file"], "error": f"{type(e).__name__}: {e}"}


class _TUExtractor:
    def __init__(self, tu, job: dict):
        self.cindex = _configure_cindex()
        ck = self.cindex.CursorKind
        tk = self.cindex.TypeKind
        self.ck, self.tk = ck, tk
        self.tu = tu
        self.job = job
        self.include_system = job.get("include_system", False)
        self.lang = job["lang"]
        self.FUNC_KINDS = {ck.FUNCTION_DECL, ck.CXX_METHOD, ck.CONSTRUCTOR, ck.DESTRUCTOR, ck.CONVERSION_FUNCTION, ck.FUNCTION_TEMPLATE}
        self.METHOD_KINDS = {ck.CXX_METHOD, ck.CONSTRUCTOR, ck.DESTRUCTOR, ck.CONVERSION_FUNCTION}
        self.SCOPE_KINDS = {ck.NAMESPACE, ck.LINKAGE_SPEC, ck.STRUCT_DECL, ck.CLASS_DECL, ck.UNION_DECL,
                            ck.CLASS_TEMPLATE, ck.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION, ck.UNEXPOSED_DECL}
        self.QUAL_KINDS = {ck.NAMESPACE, ck.STRUCT_DECL, ck.CLASS_DECL, ck.UNION_DECL, ck.CLASS_TEMPLATE, ck.ENUM_DECL}
        self.RECORD_KINDS = {ck.STRUCT_DECL: "struct", ck.UNION_DECL: "union", ck.CLASS_DECL: "class",
                             ck.CLASS_TEMPLATE: "class"}
        self.PTR_KINDS = {tk.POINTER, tk.LVALUEREFERENCE, tk.RVALUEREFERENCE, tk.MEMBERPOINTER, tk.BLOCKPOINTER}
        self.ARR_KINDS = {tk.CONSTANTARRAY, tk.INCOMPLETEARRAY, tk.VARIABLEARRAY, tk.DEPENDENTSIZEDARRAY, tk.VECTOR}
        self.FN_TYPE_KINDS = {tk.FUNCTIONPROTO, tk.FUNCTIONNOPROTO}
        self.PASS_KINDS = {ck.UNEXPOSED_EXPR, ck.PAREN_EXPR, ck.MEMBER_REF_EXPR, ck.CSTYLE_CAST_EXPR,
                           ck.CXX_STATIC_CAST_EXPR, ck.CXX_REINTERPRET_CAST_EXPR, ck.CXX_CONST_CAST_EXPR,
                           ck.CXX_FUNCTIONAL_CAST_EXPR}
        self.src_cache: dict[str, bytes] = {}
        self.macro_spans: dict[str, list[tuple[int, int, str]]] = {}
        self._op_api = _operator_api(self.cindex)
        self._op_spell_cache: dict[tuple[str, int], str] = {}
        self.functions: dict[str, dict] = {}
        self.decls: dict[str, dict] = {}
        self.vars: dict[str, dict] = {}
        self.types: dict[str, dict] = {}
        self._types_in_progress: set[str] = set()
        self._anon_hint: list[str] = []          # stack of "<parent>.<member>" while recording fields

    # ------------------------------------------------------------- utilities
    def _file_of(self, cursor) -> Optional[str]:
        f = cursor.location.file
        return f.name if f is not None else None

    def _is_system(self, cursor) -> bool:
        try:
            if cursor.location.is_in_system_header:
                return True
        except AttributeError:
            pass
        f = self._file_of(cursor)
        return bool(f) and f.startswith(SYSTEM_PREFIXES)

    def _src(self, path: str) -> bytes:
        b = self.src_cache.get(path)
        if b is None:
            try:
                with open(path, "rb") as fh:
                    b = fh.read()
            except OSError:
                b = b""
            self.src_cache[path] = b
        return b

    def _text(self, cursor) -> str:
        ext = cursor.extent
        f = ext.start.file
        if f is None:
            return clean_spelling(cursor.spelling or "")
        data = self._src(f.name)
        s, e = ext.start.offset, ext.end.offset
        if e <= s or e > len(data):
            return clean_spelling(cursor.spelling or "")
        return clean_spelling(data[s:e].decode("utf-8", "replace"))

    def _loc(self, cursor, end: bool = False) -> Optional[dict]:
        f = self._file_of(cursor)
        if not f:
            return None
        d = {"file": f, "line": cursor.location.line, "col": cursor.location.column}
        if end:
            d["end_line"] = cursor.extent.end.line
        return d

    def _qualname(self, cursor) -> str:
        parts = [cursor.spelling or "(anonymous)"]
        p = cursor.semantic_parent
        guard = 0
        while p is not None and p.kind != self.ck.TRANSLATION_UNIT and guard < 32:
            if p.kind in self.QUAL_KINDS:
                parts.insert(0, p.spelling or "(anonymous)")
            p = p.semantic_parent
            guard += 1
        return "::".join(parts)

    # ------------------------------------------------------------- run
    def run(self) -> dict:
        ck = self.ck
        top = list(self.tu.cursor.get_children())
        for c in top:
            if c.kind == ck.MACRO_INSTANTIATION:
                f = self._file_of(c)
                if f:
                    self.macro_spans.setdefault(f, []).append((c.extent.start.offset, c.extent.end.offset, c.spelling))
        self._visit_decls(top)
        deps = [self.job["file"]] + [inc.include.name for inc in self.tu.get_includes() if inc.include is not None]
        diags = []
        for d in self.tu.diagnostics:
            if d.severity >= self.cindex.Diagnostic.Error:
                f = d.location.file
                diags.append({"severity": int(d.severity), "message": d.spelling,
                              "file": f.name if f else None, "line": d.location.line})
        return {
            "file": self.job["file"], "lang": self.lang,
            "functions": self.functions, "decls": self.decls, "vars": self.vars, "types": self.types,
            "deps": TUCache.snapshot_deps(dict.fromkeys(deps)),
            "diagnostics": diags[:50], "n_errors": len(diags),
        }

    def _visit_decls(self, cursors) -> None:
        ck = self.ck
        for c in cursors:
            if c.location.file is None:
                continue
            if not self.include_system and self._is_system(c):
                continue
            if c.kind in self.FUNC_KINDS:
                if c.is_definition():
                    self._function(c)
            elif c.kind in self.SCOPE_KINDS:
                self._visit_decls(list(c.get_children()))

    # ------------------------------------------------------------- functions
    def _function(self, c) -> None:
        usr = c.get_usr()
        if not usr or usr in self.functions:
            return
        ck = self.ck
        name = c.spelling
        qualname = self._qualname(c) if self.lang == "cpp" else name
        params, type_usrs = [], []
        for a in c.get_arguments():
            t = a.type
            tref = self._type_ref(t)
            if tref:
                type_usrs.append(tref)
            params.append({"name": a.spelling, "type": clean_spelling(t.spelling), "type_usr": tref,
                           "dir": self._dir_heuristic(t), "dir_source": "heuristic"})
        rt = c.result_type
        rref = self._type_ref(rt)
        if rref:
            type_usrs.append(rref)
        ptxt = ", ".join((f"{p['type']} {p['name']}".strip()) for p in params)
        try:
            variadic = c.type.is_function_variadic()
        except Exception:  # noqa: BLE001
            variadic = False
        if variadic:
            ptxt = (ptxt + ", ..." if ptxt else "...")
        if not ptxt and self.lang == "c":
            ptxt = "void"
        signature = f"{clean_spelling(rt.spelling)} {qualname}({ptxt})"
        sc = c.storage_class
        storage = "static" if sc == self.cindex.StorageClass.STATIC else "extern"
        body = None
        for ch in c.get_children():
            if ch.kind == ck.COMPOUND_STMT:
                body = ch
        ctx = {"callsites": [], "reads": [], "writes": [], "fn_refs": [], "func": c, "func_name": qualname}
        if body is not None:
            self._walk(body, ctx, False, False)
            bh = _ids.body_hash(self._raw(body), self.lang)
        else:
            bh = _ids.body_hash(self._raw(c), self.lang)
        for cs in ctx["fn_refs"]:
            ctx["callsites"].append(cs)
        self.functions[usr] = {
            "usr": usr, "name": name, "qualname": qualname,
            "kind": "method" if c.kind in self.METHOD_KINDS else "function",
            "loc": self._loc(c, end=True), "signature": signature, "storage": storage,
            "returns": {"type": clean_spelling(rt.spelling), "type_usr": rref},
            "params": params, "body_hash": bh, "callsites": ctx["callsites"],
            "globals": {"reads": _uniq(ctx["reads"]), "writes": _uniq(ctx["writes"])},
            "type_usrs": _uniq(type_usrs), "system": self._is_system(c),
        }
        # the definition is also its own declaration
        self.decls.setdefault(usr, {"name": name, "qualname": qualname, "ptypes": [p["type"] for p in params],
                                    "loc": self._loc(c), "system": self._is_system(c)})

    def _raw(self, cursor) -> bytes:
        ext = cursor.extent
        f = ext.start.file
        if f is None:
            return b""
        data = self._src(f.name)
        return data[ext.start.offset:ext.end.offset]

    def _dir_heuristic(self, t) -> str:
        tc = t.get_canonical()
        k = tc.kind
        if k in self.PTR_KINDS:
            pointee = tc.get_pointee()
            if pointee.kind in self.FN_TYPE_KINDS:
                return "in"
            return "in" if pointee.is_const_qualified() else "inout"
        if k in self.ARR_KINDS:
            if tc.is_const_qualified():
                return "in"
            try:
                elem = tc.element_type
            except Exception:  # noqa: BLE001
                return "inout"
            return "in" if elem.is_const_qualified() else "inout"
        return "in"

    # ------------------------------------------------------------- body walk
    def _walk(self, c, ctx: dict, write_ctx: bool, callee_ctx: bool) -> None:
        ck = self.ck
        kind = c.kind
        if kind == ck.CALL_EXPR:
            self._callsite(c, ctx)
            children = list(c.get_children())
            for i, ch in enumerate(children):
                self._walk(ch, ctx, False, i == 0)
            return
        if kind == ck.DECL_REF_EXPR:
            ref = c.referenced
            if ref is None:
                return
            if ref.kind == ck.VAR_DECL and self._is_global(ref):
                usr = self._record_var(ref, ctx)
                if usr:
                    (ctx["writes"] if write_ctx else ctx["reads"]).append(usr)
            elif ref.kind in self.FUNC_KINDS and not callee_ctx:
                ref = self._primary_template(ref) or ref
                usr = ref.get_usr()
                if usr:
                    self._record_decl(ref)
                    ctx["fn_refs"].append({"callee_usr": usr, "name": ref.spelling, "loc": self._loc(c),
                                           "kind": "ref", "args": [], "macro": None, "ptr_type": None})
            return
        if kind == ck.BINARY_OPERATOR:
            children = list(c.get_children())
            if len(children) == 2 and self._binop(c, children) == "=":
                self._walk(children[0], ctx, True, False)
                self._walk(children[1], ctx, False, False)
                return
        elif kind == ck.COMPOUND_ASSIGNMENT_OPERATOR:
            children = list(c.get_children())
            if len(children) == 2:
                self._walk(children[0], ctx, True, False)
                self._walk(children[0], ctx, False, False)
                self._walk(children[1], ctx, False, False)
                return
        elif kind == ck.UNARY_OPERATOR:
            children = list(c.get_children())
            if len(children) == 1:
                op = self._unop(c, children[0])
                if op in ("++", "--"):
                    self._walk(children[0], ctx, True, False)
                    self._walk(children[0], ctx, False, False)
                    return
                if op == "&":
                    self._walk(children[0], ctx, True, False)
                    return
                self._walk(children[0], ctx, write_ctx, False)  # deref etc.
                return
        elif kind == ck.ARRAY_SUBSCRIPT_EXPR:
            children = list(c.get_children())
            for i, ch in enumerate(children):
                self._walk(ch, ctx, write_ctx if i == 0 else False, False)
            return
        inherit = kind in self.PASS_KINDS
        for ch in c.get_children():
            self._walk(ch, ctx, write_ctx if inherit else False, callee_ctx if inherit else False)

    def _op_spelling(self, which: str, c) -> Optional[str]:
        """Operator spelling via libclang's C API (exact, works inside macro expansions)."""
        api = self._op_api
        if api is None:
            return None
        kind_fn, spell_fn = api[which]
        k = kind_fn(c)
        if not k:
            return None
        key = (which, k)
        sp = self._op_spell_cache.get(key)
        if sp is None:
            sp = spell_fn(k)
            self._op_spell_cache[key] = sp
        return sp

    def _binop(self, c, children) -> Optional[str]:
        sp = self._op_spelling("binary", c)
        if sp is not None:
            return sp
        f = c.extent.start.file
        lhs_end = children[0].extent.end.offset
        rhs_start = children[1].extent.start.offset
        if f is None or rhs_start <= lhs_end:
            return None  # inside a macro expansion and no operator API: assume read (documented approximation)
        between = self._src(f.name)[lhs_end:rhs_start].decode("utf-8", "replace")
        if "/*" not in between and "//" not in between:
            return between.strip() or None
        for tok in c.get_tokens():
            off = tok.extent.start.offset
            if lhs_end <= off < rhs_start:
                return tok.spelling
        return None

    def _unop(self, c, child) -> Optional[str]:
        sp = self._op_spelling("unary", c)
        if sp is not None:
            return sp
        f = c.extent.start.file
        if f is None:
            return None
        data = self._src(f.name)
        cs, ce = c.extent.start.offset, c.extent.end.offset
        ks, ke = child.extent.start.offset, child.extent.end.offset
        if ks > cs:
            return data[cs:ks].decode("utf-8", "replace").strip() or None
        if ce > ke:
            return data[ke:ce].decode("utf-8", "replace").strip() or None
        return None

    def _macro_at(self, cursor) -> Optional[str]:
        f = self._file_of(cursor)
        if not f:
            return None
        off = cursor.extent.start.offset
        for s, e, name in self.macro_spans.get(f, ()):
            if s <= off <= e:
                return name
        return None

    def _primary_template(self, ref):
        """For a call to `clamp<uint32_t>(…)` libclang references the implicit specialization, whose USR has no
        definition anywhere; map it back to the function template (or class-template method) that does."""
        try:
            t = self.cindex.conf.lib.clang_getSpecializedCursorTemplate(ref)
        except Exception:  # noqa: BLE001 - binding missing in an old libclang
            return None
        if t is None or t.kind not in self.FUNC_KINDS:
            return None
        return t

    def _callsite(self, c, ctx: dict) -> None:
        ref = c.referenced
        macro = self._macro_at(c)
        loc = self._loc(c)
        if macro:
            args = _split_macro_args(self._text(c))
        else:
            args = [self._text(a) for a in c.get_arguments()]
        if ref is not None and ref.kind in self.FUNC_KINDS:
            ref = self._primary_template(ref) or ref
            usr = ref.get_usr()
            self._record_decl(ref)
            ctx["callsites"].append({"callee_usr": usr, "name": ref.spelling, "loc": loc,
                                     "kind": "macro" if macro else "call", "args": args,
                                     "macro": macro, "ptr_type": None})
            return
        children = list(c.get_children())
        callee = children[0] if children else None
        name = self._text(callee) if callee is not None else (c.spelling or "<indirect>")
        ptr_type = None
        try:
            if ref is not None:
                ptr_type = clean_spelling(ref.type.spelling)
            elif callee is not None:
                ptr_type = clean_spelling(callee.type.spelling)
        except Exception:  # noqa: BLE001
            ptr_type = None
        if not name or name.startswith("<"):
            name = c.spelling or "<indirect>"
        ctx["callsites"].append({"callee_usr": None, "name": name, "loc": loc, "kind": "fnptr",
                                 "args": args, "macro": macro, "ptr_type": ptr_type})

    def _record_decl(self, ref) -> None:
        usr = ref.get_usr()
        if not usr or usr in self.decls:
            return
        try:
            ptypes = [clean_spelling(t.spelling) for t in ref.type.argument_types()]
        except Exception:  # noqa: BLE001 - not a function type (e.g. a variable referenced through a template)
            ptypes = []
        self.decls[usr] = {"name": ref.spelling,
                           "qualname": self._qualname(ref) if self.lang == "cpp" else ref.spelling,
                           "ptypes": ptypes, "loc": self._loc(ref), "system": self._is_system(ref)}

    # ------------------------------------------------------------- globals
    def _is_global(self, var) -> bool:
        ck = self.ck
        sp = var.semantic_parent
        if sp is None:
            return False
        if sp.kind in (ck.TRANSLATION_UNIT, ck.NAMESPACE, ck.LINKAGE_SPEC):
            return True
        if sp.kind in (ck.STRUCT_DECL, ck.CLASS_DECL, ck.CLASS_TEMPLATE):
            return True
        return var.storage_class == self.cindex.StorageClass.STATIC

    def _record_var(self, var, ctx: dict) -> Optional[str]:
        usr = var.get_usr()
        if not usr:
            return None
        if usr in self.vars:
            return usr
        ck = self.ck
        sp = var.semantic_parent
        if sp is not None and sp.kind in self.FUNC_KINDS:
            scope, qual = "function-static", f"{ctx['func_name']}.{var.spelling}"
        elif sp is not None and sp.kind in (ck.STRUCT_DECL, ck.CLASS_DECL, ck.CLASS_TEMPLATE):
            scope, qual = "member", self._qualname(var)
        else:
            scope, qual = "file", (self._qualname(var) if self.lang == "cpp" else var.spelling)
        t = var.type
        tref = self._type_ref(t)
        sc = var.storage_class
        storage = {self.cindex.StorageClass.STATIC: "static", self.cindex.StorageClass.EXTERN: "extern"}.get(sc, "extern")
        self.vars[usr] = {"name": var.spelling, "qualname": qual, "loc": self._loc(var), "type": clean_spelling(t.spelling),
                          "type_usr": tref, "storage": storage, "scope": scope, "system": self._is_system(var)}
        return usr

    # ------------------------------------------------------------- types
    def _type_ref(self, t) -> Optional[str]:
        guard = 0
        while guard < 16:
            k = t.kind
            if k in self.PTR_KINDS:
                t = t.get_pointee()
            elif k in self.ARR_KINDS:
                try:
                    t = t.element_type
                except Exception:  # noqa: BLE001
                    return None
            else:
                break
            guard += 1
        if t.kind in self.FN_TYPE_KINDS:
            return None
        decl = t.get_declaration()
        if decl is None or decl.kind == self.ck.NO_DECL_FOUND:
            return None
        return self._record_type(decl)

    def _record_type(self, decl) -> Optional[str]:
        usr = decl.get_usr()
        if not usr:
            return None
        if usr in self.types or usr in self._types_in_progress:
            return usr
        self._types_in_progress.add(usr)
        ck = self.ck
        kind = decl.kind
        system = self._is_system(decl)
        spelling = decl.spelling or ""
        anonymous = (not spelling) or "(unnamed" in spelling or "(anonymous" in spelling
        try:
            anonymous = anonymous or bool(decl.is_anonymous())
        except Exception:  # noqa: BLE001
            pass
        anon_name = self._anon_hint[-1] if (anonymous and self._anon_hint) else ""
        entry = {"name": "" if anonymous else spelling,
                 "qualname": anon_name if anonymous else (self._qualname(decl) if self.lang == "cpp" else spelling),
                 "loc": self._loc(decl), "system": system, "anonymous": anonymous,
                 "size": None, "align": None, "fields": [], "enumerators": [],
                 "underlying": None, "underlying_usr": None, "field_usrs": []}
        t = decl.type
        size = t.get_size()
        align = t.get_align()
        entry["size"] = size if size >= 0 else None
        entry["align"] = align if align >= 0 else None
        if kind in (ck.TYPEDEF_DECL, ck.TYPE_ALIAS_DECL):
            entry["kind"] = "typedef"
            ut = decl.underlying_typedef_type
            entry["underlying"] = clean_spelling(ut.spelling)
            entry["underlying_usr"] = self._type_ref(ut)
        elif kind in self.RECORD_KINDS:
            entry["kind"] = self.RECORD_KINDS[kind]
            defn = decl if decl.is_definition() else decl.get_definition()
            if defn is not None and defn.kind != ck.NO_DECL_FOUND and (self.include_system or not system):
                parent_name = anon_name or (self._qualname(decl) if self.lang == "cpp" else spelling) or f"anon@L{(self._loc(decl) or {}).get('line', 0)}"
                for i, f in enumerate(defn.type.get_fields()):
                    ft = f.type
                    self._anon_hint.append(f"{parent_name}.{member_name(f.spelling) or f'(anon#{i})'}")
                    try:
                        fref = self._type_ref(ft)
                    finally:
                        self._anon_hint.pop()
                    bits = f.get_field_offsetof()
                    fld = {"name": member_name(f.spelling), "type": clean_spelling(ft.spelling), "type_usr": fref,
                           "offset": bits // 8 if bits >= 0 else None, "size": None,
                           "bit_offset": None, "bit_width": None}
                    if f.is_bitfield():
                        fld["bit_width"] = f.get_bitfield_width()
                        fld["bit_offset"] = bits % 8 if bits >= 0 else None
                    else:
                        fs = ft.get_size()
                        fld["size"] = fs if fs >= 0 else None
                    entry["fields"].append(fld)
                    if fref:
                        entry["field_usrs"].append(fref)
            elif defn is None or defn.kind == ck.NO_DECL_FOUND:
                entry["incomplete"] = True
        elif kind == ck.ENUM_DECL:
            entry["kind"] = "enum"
            try:
                entry["underlying"] = clean_spelling(decl.enum_type.spelling)
            except Exception:  # noqa: BLE001
                pass
            for ch in decl.get_children():
                if ch.kind == ck.ENUM_CONSTANT_DECL:
                    entry["enumerators"].append({"name": ch.spelling, "value": ch.enum_value})
        else:
            entry["kind"] = kind.name.lower()
        self.types[usr] = entry
        self._types_in_progress.discard(usr)
        return usr


_OP_API_CACHE: dict = {}


def _operator_api(cindex):
    """(kind_fn, spelling_fn) pairs for binary/unary operators, or None if this libclang predates them (< 17)."""
    lib = cindex.conf.lib
    if id(lib) in _OP_API_CACHE:
        return _OP_API_CACHE[id(lib)]
    import ctypes
    try:
        out = {}
        for which, kind_name, spell_name in (
            ("binary", "clang_getCursorBinaryOperatorKind", "clang_getBinaryOperatorKindSpelling"),
            ("unary", "clang_getCursorUnaryOperatorKind", "clang_getUnaryOperatorKindSpelling"),
        ):
            kind_fn = getattr(lib, kind_name)
            kind_fn.argtypes = [cindex.Cursor]
            kind_fn.restype = ctypes.c_uint
            spell_fn = getattr(lib, spell_name)
            spell_fn.argtypes = [ctypes.c_uint]
            spell_fn.restype = cindex._CXString
            spell_fn.errcheck = cindex._CXString.from_result
            out[which] = (kind_fn, spell_fn)
        api = out
    except (AttributeError, TypeError):
        api = None
    _OP_API_CACHE[id(lib)] = api
    return api


def _uniq(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _split_macro_args(text: str) -> list[str]:
    """'MAC(a, f(b, c), d)' -> ['a', 'f(b, c)', 'd']"""
    i = text.find("(")
    if i < 0 or not text.rstrip().endswith(")"):
        return []
    inner = text[i + 1:text.rstrip().rfind(")")]
    out, depth, cur = [], 0, []
    for ch in inner:
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


# ============================================================ merged index + Frontend

class ClangFrontend(Frontend):
    lang = "c"

    def __init__(self, root: str, compile_commands_dir: str, *, extra_args: list[str] | None = None,
                 include_system: bool = False, cache_dir: Optional[str] = None, use_cache: bool = True,
                 jobs: Optional[int] = None, resource_dir: Optional[str] = None, verbose: bool = False):
        self.root = os.path.abspath(root)
        self.cc_dir = compile_commands_dir
        self.extra_args = list(extra_args or [])
        self.include_system = include_system
        self.verbose = verbose
        self.jobs = jobs or max(1, (os.cpu_count() or 2) - 1)
        self.resource_dir = detect_resource_dir(resource_dir)
        self.cache = TUCache(cache_dir or os.path.join(self.root, ".hx", "cache"), enabled=use_cache)
        self.functions: dict[str, dict] = {}
        self.decls: dict[str, dict] = {}
        self.vars: dict[str, dict] = {}
        self.types: dict[str, dict] = {}
        self.callers_idx: dict[str, list[tuple[str, dict]]] = {}
        self.ids: dict[str, str] = {}
        self.type_ids: dict[str, str] = {}
        self.var_ids: dict[str, str] = {}
        self.stats: dict = {}
        self.errors: list[dict] = []
        self.diagnostics: list[dict] = []
        self.notes: list[str] = []
        self.variants: dict[str, dict[tuple, list[str]]] = {}   # usr -> {variant signature: [TU files]} when TUs disagree

    def _cache_extra(self) -> tuple:
        """Everything besides (file, args) that shapes a summary — all of it must be in the cache key."""
        return (SUMMARY_VERSION, self.root, int(self.include_system))

    # ------------------------------------------------------------- index
    def build_index(self) -> None:
        t0 = time.time()
        jobs = load_jobs(self.cc_dir, self.extra_args, self.resource_dir)
        if jobs:
            self.lang = "cpp" if all(j.lang == "cpp" for j in jobs) else "c"
        summaries: list[dict] = []
        todo: list[dict] = []
        extra = self._cache_extra()
        for j in jobs:
            s = self.cache.load(j.file, j.args, extra)
            if s is not None:
                summaries.append(s)
            else:
                todo.append({"file": j.file, "args": j.args, "lang": j.lang, "root": self.root,
                             "include_system": self.include_system})
        if todo:
            if self.jobs > 1 and len(todo) > 1:
                with ProcessPoolExecutor(max_workers=min(self.jobs, len(todo))) as ex:
                    results = list(ex.map(parse_tu, todo, chunksize=1))
            else:
                results = [parse_tu(j) for j in todo]
            for j, r in zip(todo, results):
                if "error" in r:
                    self.errors.append(r)
                    continue
                self.cache.store(j["file"], j["args"], r, extra)
                summaries.append(r)
        self._merge(summaries)
        self.stats = {"tus": len(jobs), "parsed": len(todo) - len(self.errors), "cached": len(jobs) - len(todo),
                      "tu_errors": len(self.errors), "diagnostics": sum(s.get("n_errors", 0) for s in summaries),
                      "index_seconds": round(time.time() - t0, 2), "resource_dir": self.resource_dir,
                      "functions_indexed": len(self.functions), "types_indexed": len(self.types),
                      "variants": len(self.variants)}

    @staticmethod
    def _same_file(a: Optional[str], b: Optional[str]) -> bool:
        return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))

    def _merge(self, summaries: list[dict]) -> None:
        """Fold per-TU summaries into one index. The result must not depend on which TUs came from the
        cache, so summaries are merged in TU-path order and, for a function seen in several TUs (inline /
        header-defined), the TU that *is* the defining file wins, else the first TU in that order."""
        owner: dict[str, str] = {}                       # usr -> TU file whose summary we kept
        shapes: dict[str, dict[tuple, list[str]]] = {}   # usr -> {(body_hash, callees): [TU files]}

        def shape(f: dict) -> tuple:
            return (f.get("body_hash"), tuple(c.get("callee_usr") or c.get("name") for c in f["callsites"]))

        for s in sorted(summaries, key=lambda x: os.path.normcase(os.path.abspath(x["file"]))):
            lang = s["lang"]
            tu = s["file"]
            for usr, f in s["functions"].items():
                shapes.setdefault(usr, {}).setdefault(shape(f), []).append(tu)
                prev = self.functions.get(usr)
                if prev is not None:
                    if not (self._same_file(tu, f["loc"]["file"]) and not self._same_file(owner[usr], prev["loc"]["file"])):
                        continue                           # keep the earlier one unless this TU owns the definition
                f = dict(f)
                f["lang"] = lang
                self.functions[usr] = f
                owner[usr] = tu
            for usr, d in s["decls"].items():
                if usr not in self.decls:
                    d = dict(d)
                    d["lang"] = lang
                    self.decls[usr] = d
            for usr, v in s["vars"].items():
                if usr not in self.vars:
                    v = dict(v)
                    v["lang"] = lang
                    self.vars[usr] = v
            for usr, t in s["types"].items():
                prev = self.types.get(usr)
                if prev is None or (not prev.get("fields") and t.get("fields")):
                    t = dict(t)
                    t["lang"] = lang
                    self.types[usr] = t
            for d in s.get("diagnostics", []):
                self.diagnostics.append(d)
        self.variants = {usr: sh for usr, sh in shapes.items() if len(sh) > 1}
        for usr, sh in sorted(self.variants.items(), key=lambda kv: self.functions[kv[0]]["qualname"])[:8]:
            f = self.functions[usr]
            others = sorted({_ids.rel(t, self.root) for tus in sh.values() for t in tus if t != owner[usr]})
            self.notes.append(f"{f['qualname']}: compiled differently in {len(sh)} build variants "
                              f"(using {_ids.rel(owner[usr], self.root)}; others: " + ", ".join(others[:3])
                              + (" …" if len(others) > 3 else "") + ")")
        if len(self.variants) > 8:
            self.notes.append(f"… {len(self.variants) - 8} more functions differ between build variants")
        # callers index
        for usr, f in self.functions.items():
            for cs in f["callsites"]:
                if cs.get("callee_usr"):
                    self.callers_idx.setdefault(cs["callee_usr"], []).append((usr, cs))
        # stable ids. C++ functions always carry their parameter type list (overloads), so an id never changes
        # because a sibling overload appeared; a #hash is added only on a residual collision (review finding H5).
        def symbol(rec: dict, ptypes: list[str]) -> str:
            if rec["lang"] == "cpp":
                return f"{rec['qualname']}({', '.join(ptypes)})"
            return rec["qualname"]
        cand = {}
        for usr, f in self.functions.items():
            cand[usr] = _ids.node_id(f["lang"], _ids.rel(f["loc"]["file"], self.root), symbol(f, [p["type"] for p in f["params"]]))
        self.ids = _ids.disambiguate(cand)
        for usr, d in self.decls.items():
            if usr in self.ids or not d.get("loc"):
                continue
            self.ids[usr] = _ids.node_id(d["lang"], _ids.rel(d["loc"]["file"], self.root), symbol(d, d.get("ptypes") or []))
        for usr, v in self.vars.items():
            self.var_ids[usr] = _ids.var_id(v["lang"], _ids.rel(v["loc"]["file"], self.root) if v.get("loc") else "?", v["qualname"])
        for usr, t in self.types.items():
            relp = _ids.rel(t["loc"]["file"], self.root) if t.get("loc") else "?"
            line = t["loc"]["line"] if t.get("loc") else None
            if t["anonymous"] and t.get("qualname"):
                self.type_ids[usr] = _ids.type_id(t["lang"], relp, t["kind"], t["qualname"])   # e.g. "union dma_chan.stat"
            else:
                self.type_ids[usr] = _ids.type_id(t["lang"], relp, t["kind"], t.get("qualname") or t["name"],
                                                  anonymous=t["anonymous"], line=line)

    # ------------------------------------------------------------- Frontend API
    def _mkloc(self, d: Optional[dict]) -> Optional[Loc]:
        if not d:
            return None
        return Loc(file=_ids.rel(d["file"], self.root), line=d["line"], end_line=d.get("end_line"), col=d.get("col"))

    def locate_entry(self, file: str, symbol: str) -> str:
        abs_file = os.path.abspath(file if os.path.isabs(file) else os.path.join(self.root, file))
        if not os.path.exists(abs_file) and os.path.exists(os.path.abspath(file)):
            abs_file = os.path.abspath(file)

        def same(a: Optional[str]) -> bool:
            return bool(a) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(abs_file)

        cands = [u for u, f in self.functions.items() if f["name"] == symbol or f["qualname"] == symbol]
        in_file = [u for u in cands if same(self.functions[u]["loc"]["file"])]
        if in_file:
            return in_file[0]
        declared_here = [u for u in cands if u in self.decls and same((self.decls[u].get("loc") or {}).get("file"))]
        if declared_here:
            return declared_here[0]
        if len(cands) == 1:
            where = _ids.rel(self.functions[cands[0]]["loc"]["file"], self.root)
            self.notes.append(f"'{symbol}' is not defined in {file}; using its definition in {where}")
            return cands[0]
        if len(cands) > 1:
            where = ", ".join(_ids.rel(self.functions[u]["loc"]["file"], self.root) for u in cands)
            raise EntryNotFound(f"'{symbol}' is defined in several files ({where}); none is {file}", [self.ids[u] for u in cands])
        import difflib
        names = sorted({f["qualname"] for f in self.functions.values()})
        sugg = difflib.get_close_matches(symbol, names, n=5, cutoff=0.6)
        hint = ""
        if not any(same(f["loc"]["file"]) for f in self.functions.values()):
            hint = f" No function definitions were indexed from {file}: is it (or a TU including it) in compile_commands.json?"
        raise EntryNotFound(f"function '{symbol}' not found in the indexed project.{hint}", sugg)

    def stable_id(self, key: str) -> Optional[str]:
        return self.ids.get(key)

    def function(self, key: str) -> Optional[FunctionRecord]:
        f = self.functions.get(key)
        if f is None:
            return None
        node = Node(
            id=self.ids[key], kind=f["kind"], name=f["name"], qualname=f["qualname"], lang=f["lang"],
            loc=self._mkloc(f["loc"]), signature=f["signature"], storage=f["storage"], body_hash=f["body_hash"],
            precision="exact",
            returns=TypeUse(type=f["returns"]["type"], type_ref=self.type_ids.get(f["returns"]["type_usr"] or "")),
            params=[Param(name=p["name"], type=p["type"], type_ref=self.type_ids.get(p["type_usr"] or ""),
                          dir=p["dir"], dir_source=p["dir_source"]) for p in f["params"]],
            globals=GlobalRefs(reads=[self.var_ids[u] for u in f["globals"]["reads"] if u in self.var_ids],
                               writes=[self.var_ids[u] for u in f["globals"]["writes"] if u in self.var_ids]),
        )
        callsites = [CallSite(callee_key=cs.get("callee_usr"), name=cs["name"], loc=self._mkloc(cs.get("loc")),
                              kind=cs["kind"], args=list(cs.get("args", [])), macro=cs.get("macro"),
                              ptr_type=cs.get("ptr_type")) for cs in f["callsites"]]
        type_keys = list(f["type_usrs"])
        global_keys = _uniq(f["globals"]["reads"] + f["globals"]["writes"])
        for gk in global_keys:
            v = self.vars.get(gk)
            if v and v.get("type_usr"):
                type_keys.append(v["type_usr"])
        return FunctionRecord(node=node, callsites=callsites, type_keys=_uniq(type_keys), global_keys=global_keys)

    def declaration(self, key: str) -> Optional[DeclRecord]:
        f = self.functions.get(key)
        d = self.decls.get(key)
        src = f or d
        if src is None:
            return None
        loc = src.get("loc")
        return DeclRecord(id=self.ids.get(key, key), name=src["name"], loc=self._mkloc(loc),
                          has_definition=f is not None, system=bool(src.get("system")),
                          relpath=_ids.rel(loc["file"], self.root) if loc else None)

    def type(self, key: str) -> Optional[TypeRecord]:
        t = self.types.get(key)
        if t is None:
            return None
        td = TypeDef(
            id=self.type_ids[key], kind=t["kind"], name=(t.get("qualname") or t["name"] or f"(anonymous {t['kind']})"),
            lang=t["lang"], loc=self._mkloc(t.get("loc")), size=t.get("size"), align=t.get("align"),
            fields=[Field(name=fl["name"], type=fl["type"], type_ref=self.type_ids.get(fl["type_usr"] or ""),
                          offset=fl["offset"], size=fl["size"], bit_offset=fl["bit_offset"], bit_width=fl["bit_width"])
                    for fl in t.get("fields", [])],
            enumerators=[Enumerator(name=e["name"], value=e["value"]) for e in t.get("enumerators", [])],
            underlying=t.get("underlying"), underlying_ref=self.type_ids.get(t.get("underlying_usr") or ""),
            anonymous=t["anonymous"], system=bool(t.get("system")),
        )
        return TypeRecord(typedef=td, nested_keys=list(t.get("field_usrs", [])),
                          alias_keys=[t["underlying_usr"]] if t.get("underlying_usr") else [])

    def global_var(self, key: str) -> Optional[GlobalVar]:
        v = self.vars.get(key)
        if v is None:
            return None
        return GlobalVar(id=self.var_ids[key], name=v["name"], type=v["type"], lang=v["lang"],
                         type_ref=self.type_ids.get(v.get("type_usr") or ""), loc=self._mkloc(v.get("loc")),
                         storage=v.get("storage"), scope=v.get("scope", "file"))

    def callers(self, key: str) -> list[tuple[str, CallSite]]:
        out = []
        for caller_usr, cs in self.callers_idx.get(key, []):
            out.append((caller_usr, CallSite(callee_key=key, name=cs["name"], loc=self._mkloc(cs.get("loc")),
                                             kind=cs["kind"], args=list(cs.get("args", [])), macro=cs.get("macro"),
                                             ptr_type=cs.get("ptr_type"))))
        return out
