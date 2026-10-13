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
import importlib.metadata
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
from .. import __version__ as _HX_VERSION
from ..cache import TUCache

# Bump whenever the per-TU summary format or the hashing/ID rules change: it is part of the cache key,
# so stale .hx/cache entries from an older hx can never be mixed with fresh ones.
#   3 (0.4.0): call-site `args` come from the recorded macro span / literal-preserving `squash_ws` (review C2, C3).
#   4 (0.4.0): keys of non-external symbols and all types are scoped by file (`usr@/real/path`); type records carry
#              `usr`, `chain` and `definition_file` provenance (review C1, hx/3).
SUMMARY_VERSION = 5
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
        src_abs = _ids.realpath(_abs(source, directory))
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
        self.TYPE_DECL_KINDS = set(self.RECORD_KINDS) | {ck.ENUM_DECL, ck.TYPEDEF_DECL, ck.TYPE_ALIAS_DECL}
        self._decl_files: dict[str, dict[str, list[int]]] = {}   # raw type USR -> {file declaring or naming it: [line, col]}

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

    def _key(self, cursor, kind: str) -> str:
        """Index key of a symbol (review finding C1). libclang's USR is unique only for external linkage: a static
        function in `a/options.c` and one in `b/options.c` both get `c:options.c@F@name`, a file-scope struct tag gets
        no file at all (`c:@S@ctx`), and typedef / static-variable USRs carry only the file's basename. So anything that
        is not external is scoped by the real path of its defining file (`usr@/path`); extern symbols keep the bare
        USR, so C++ overload hashes do not move. Types get a PROVISIONAL key — the definition file when this TU sees
        the definition, else the first declaration's file — that `ClangFrontend._reconcile_types` settles across TUs."""
        usr = cursor.get_usr()
        if not usr:
            return ""
        nd = self.ck.NO_DECL_FOUND
        if kind == "type":
            d = cursor.get_definition()
            f = self._file_of(d) if (d is not None and d.kind != nd) else None
            if f is None:
                f = self._file_of(cursor.canonical)
            return f"{usr}@{_ids.realpath(f)}" if f else usr
        try:
            if cursor.linkage == self.cindex.LinkageKind.EXTERNAL:
                return usr
        except Exception:  # noqa: BLE001 - binding without `linkage`
            return usr
        d = cursor.get_definition()
        if d is None or d.kind == nd:
            d = cursor
        f = self._file_of(d)
        return f"{usr}@{_ids.realpath(f)}" if f else usr

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
        """Source text of an expression with formatting squashed but literals verbatim (review finding C3:
        `clean_spelling` is for TYPE spellings and would collapse the spaces inside `"   "`)."""
        ext = cursor.extent
        f = ext.start.file
        if f is None:
            return (cursor.spelling or "").strip()
        data = self._src(f.name)
        s, e = ext.start.offset, ext.end.offset
        if e <= s or e > len(data):
            return (cursor.spelling or "").strip()
        return _ids.squash_ws(data[s:e].decode("utf-8", "replace"), "c")

    def _loc(self, cursor, end: bool = False) -> Optional[dict]:
        f = self._file_of(cursor)
        if not f:
            return None
        d = {"file": f, "line": cursor.location.line, "col": cursor.location.column}
        if end:
            d["end_line"] = cursor.extent.end.line
        return d

    def _qualname(self, cursor) -> str:
        """Scope-qualified name: namespaces, enclosing records and enclosing FUNCTIONS (a type local to `f` is
        `f::local`; review round 9: two functions may each define a `struct local`)."""
        parts = [cursor.spelling or "(anonymous)"]
        p = cursor.semantic_parent
        guard = 0
        while p is not None and p.kind != self.ck.TRANSLATION_UNIT and guard < 32:
            if p.kind in self.QUAL_KINDS or p.kind in self.FUNC_KINDS:
                parts.insert(0, p.spelling or "(anonymous)")
            p = p.semantic_parent
            guard += 1
        return "::".join(parts)

    def _in_function(self, cursor) -> bool:
        p = cursor.semantic_parent
        guard = 0
        while p is not None and p.kind != self.ck.TRANSLATION_UNIT and guard < 32:
            if p.kind in self.FUNC_KINDS:
                return True
            p = p.semantic_parent
            guard += 1
        return False

    def _type_qualname(self, decl, spelling: str) -> str:
        """C++: the qualified name. C: the bare tag — unless the type is local to a function, which qualifies it
        (`f::local`), so file-scope C ids never move while two functions' `struct local` stay two types."""
        if self.lang == "cpp" or self._in_function(decl):
            return self._qualname(decl)
        return spelling

    # ------------------------------------------------------------- run
    def run(self) -> dict:
        ck = self.ck
        top = list(self.tu.cursor.get_children())
        for c in top:
            if c.kind == ck.MACRO_INSTANTIATION:
                f = self._file_of(c)
                if f:
                    self.macro_spans.setdefault(f, []).append((c.extent.start.offset, c.extent.end.offset, c.spelling))
        self._collect_decl_files(top)
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

    def _collect_decl_files(self, cursors) -> None:
        """Every file in which this TU declares OR names each type at file scope (review round 9, refined on FFmpeg):
        a chain made of the first declaration and the definition alone never links a header whose `struct x;` comes
        after the definition, and FFmpeg forward-declares its opaque types in several headers while the shared
        header only says `typedef struct x x;` — a reference, not a declaration, to libclang. Within one TU every
        file-scope `struct x` names the same type, so a declaration, a typedef target, a field type, a prototype
        parameter or a global's type are all evidence that the file's `struct x` is this TU's `struct x`.
        Recursion into namespaces and record bodies only, never into function bodies (a local tag has a
        per-function USR)."""
        ck = self.ck
        for c in cursors:
            if c.location.file is None or (not self.include_system and self._is_system(c)):
                continue
            if c.kind in self.TYPE_DECL_KINDS:
                self._note_decl_file(c, c)
                if c.kind in self.RECORD_KINDS:
                    for ch in c.get_children():
                        if ch.kind == ck.FIELD_DECL:
                            self._note_type_refs(ch)
                        elif ch.kind in self.TYPE_DECL_KINDS or ch.kind in self.SCOPE_KINDS:
                            self._collect_decl_files([ch])
                else:
                    self._note_type_refs(c)                       # typedef struct x x;
            elif c.kind in self.FUNC_KINDS or c.kind == ck.VAR_DECL:
                for ch in c.get_children():                       # parameter, return and variable types, never a body
                    if ch.kind == ck.PARM_DECL:
                        self._note_type_refs(ch)
                    elif ch.kind == ck.TYPE_REF:
                        self._note_type_ref(ch)
            elif c.kind in self.SCOPE_KINDS:
                self._collect_decl_files(list(c.get_children()))

    def _note_type_refs(self, cursor) -> None:
        for ch in cursor.get_children():
            if ch.kind == self.ck.TYPE_REF:
                self._note_type_ref(ch)

    def _note_type_ref(self, ref) -> None:
        try:
            d = ref.referenced
        except Exception:  # noqa: BLE001 - a reference libclang cannot resolve is no evidence
            return
        if d is not None and d.kind in self.TYPE_DECL_KINDS:
            self._note_decl_file(d, ref)

    def _note_decl_file(self, decl, at) -> None:
        f = self._file_of(at)
        usr = decl.get_usr() if f else ""
        if usr:
            self._decl_files.setdefault(usr, {}).setdefault(_ids.realpath(f), [at.location.line, at.location.column])

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
        usr = self._key(c, "function")
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
            "usr": c.get_usr(), "name": name, "qualname": qualname,
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
                usr = self._key(ref, "function")
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

    def _macro_span_at(self, cursor) -> Optional[tuple[int, int, str]]:
        """The recorded macro invocation `(start, end, name)` a cursor was expanded from, or None. Matched on
        `cursor.location`, which for code produced by a macro is the expansion site (the span start) — also for a
        call built from the macro's ARGUMENT tokens, whose extent collapses to a single offset."""
        f = self._file_of(cursor)
        if not f:
            return None
        off = cursor.location.offset
        for s, e, name in self.macro_spans.get(f, ()):
            if s <= off <= e:
                return s, e, name
        return None

    def _macro_args(self, c, span: tuple[int, int, str]) -> list[str]:
        """Spelled arguments of a call that comes from a macro (review finding C2; rule recorded in the SSOT):
          - the call's extent runs PAST the macro span  -> the macro produced the callee NAME (`FUNCC(x)(args)`,
            object-like `av_clip(args)`): the arguments are the parenthesised list that follows the span;
          - otherwise (wrapper macro `ff_dlog(...)` -> av_log, or a call nested inside the expansion such as
            `AV_WB32(buf1, n)` -> av_bswap32, or one built from the macro's argument tokens): the macro's own
            arguments, read from the recorded span.
        Arguments are split by `ids.paren_args`, which never splits inside a literal."""
        s, e, _ = span
        f = self._file_of(c)
        data = self._src(f)
        end_loc = c.extent.end
        end = end_loc.offset if (end_loc.file is not None and end_loc.file.name == f) else s
        if end > e:
            text = data[e:end]
        else:
            text = data[s:e]
            # an OBJECT-LIKE macro standing for a function-like one (`#define AV_WBBUF AV_WB64` then
            # `AV_WBBUF(p, v)`): the span is the bare name and the call's extent collapses, but the arguments are the
            # list that follows the span in the source
            if b"(" not in text:
                tail = data[e:e + 4096]
                if tail.lstrip()[:1] == b"(":
                    text = tail
        return _ids.paren_args(text.decode("utf-8", "replace"), "c", keep_empty=True)

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
        span = self._macro_span_at(c)
        macro = span[2] if span else None
        loc = self._loc(c)
        if span:
            args = self._macro_args(c, span)
        else:
            args = [self._text(a) for a in c.get_arguments()]
        if ref is not None and ref.kind in self.FUNC_KINDS:
            ref = self._primary_template(ref) or ref
            usr = self._key(ref, "function")
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
        usr = self._key(ref, "function")
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
        usr = self._key(var, "var")
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
        raw_usr = decl.get_usr()
        if not raw_usr:
            return None
        usr = self._key(decl, "type")                      # provisional key, settled across TUs in _merge
        if usr in self.types or usr in self._types_in_progress:
            return usr
        self._types_in_progress.add(usr)
        ck = self.ck
        kind = decl.kind
        system = self._is_system(decl)
        defn = decl.get_definition()
        if defn is not None and defn.kind == ck.NO_DECL_FOUND:
            defn = None
        if defn is None and kind in (ck.TYPEDEF_DECL, ck.TYPE_ALIAS_DECL):
            defn = decl                                   # a typedef is its own definition
        dfile = self._file_of(defn) if defn is not None else None
        cfile = self._file_of(decl.canonical)
        mentions = self._decl_files.get(raw_usr, {})
        provenance = {"usr": raw_usr,
                      "definition_file": _ids.realpath(dfile) if dfile else None,           # JSON-safe: a sorted list
                      "chain": sorted({_ids.realpath(x) for x in (cfile, dfile) if x} | set(mentions)),
                      "mentions": mentions}                                                  # file -> [line, col] of the first mention
        spelling = decl.spelling or ""
        anonymous = (not spelling) or "(unnamed" in spelling or "(anonymous" in spelling
        try:
            anonymous = anonymous or bool(decl.is_anonymous())
        except Exception:  # noqa: BLE001
            pass
        anon_name = self._anon_hint[-1] if (anonymous and self._anon_hint) else ""
        entry = {"name": "" if anonymous else spelling,
                 "qualname": anon_name if anonymous else self._type_qualname(decl, spelling),
                 "loc": self._loc(defn if defn is not None else decl), "system": system, "anonymous": anonymous,
                 "size": None, "align": None, "fields": [], "enumerators": [],
                 "underlying": None, "underlying_usr": None, "field_usrs": [], **provenance}
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
            if defn is not None and (self.include_system or not system):
                parent_name = anon_name or self._type_qualname(decl, spelling) or f"anon@L{(self._loc(decl) or {}).get('line', 0)}"
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
            elif defn is None:
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


_USR_OFFSETS = re.compile(r"@\d+")
_TYPEDEF_FILE = re.compile(r"^c:[^@]*@T@")      # the file part of a C typedef USR (`c:avio_internal.h@T@AVFormatContext`)          # byte-offset segments of a function-local USR (`c:f.c@28@F@f@S@t`)

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


def _libclang_version() -> str:
    try:
        return importlib.metadata.version("libclang")
    except Exception:  # noqa: BLE001 - not installed as a distribution (system libclang via HX_LIBCLANG)
        return "?"


# ============================================================ merged index + Frontend

class ClangFrontend(Frontend):
    lang = "c"

    def __init__(self, root: str, compile_commands_dir: str, *, extra_args: list[str] | None = None,
                 include_system: bool = False, cache_dir: Optional[str] = None, use_cache: bool = True,
                 jobs: Optional[int] = None, resource_dir: Optional[str] = None, verbose: bool = False):
        self.root = _ids.realpath(root)
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
        """Everything besides (file, args) that shapes a summary — all of it must be in the cache key, including
        the hx and libclang versions that produced it."""
        return (SUMMARY_VERSION, self.root, int(self.include_system), _HX_VERSION, _libclang_version(),
                os.environ.get("HX_LIBCLANG", ""))

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
        return bool(a and b) and os.path.normcase(_ids.realpath(a)) == os.path.normcase(_ids.realpath(b))

    # ------------------------------------------------------------- type identity across TUs
    def _reconcile_types(self, summaries: list[dict]) -> dict[tuple[str, str], str]:
        """Map every per-TU provisional type key to its final key (review findings C1/BufferSinkContext, rounds 3-8).

        1. Records sharing a raw USR are joined by union-find over their `chain` files (first declaration and
           definition as seen by that TU): a TU that saw both the stub in `fwd.h` and the definition in `complete.h`
           links the two files, whatever its include order. A class with ONE definition file is keyed by it; a class
           with none keeps its first declaration file and stays incomplete; a class with SEVERAL definition files
           (two different definitions reached through one shared forward declaration) is not merged: each definition
           keeps its own key and the stubs stay incomplete, with a note.
        2. Variants: each TU's view of a class is fingerprinted with `ids.fingerprint_types` (identity + local shape +
           resolved field/underlying targets, SCC based). A class whose complete views carry more than one
           fingerprint is split per fingerprint (`key|<8hex>`, id `…@<8hex>`); references follow the variant the
           referring TU observed; a TU that only saw a declaration borrows the unique complete view when all complete
           views agree, else keeps referring to the plain incomplete key. Nothing is guessed."""
        from collections import defaultdict
        recs: dict[tuple[str, str], dict] = {}
        by_usr: dict[str, list[tuple[str, str]]] = defaultdict(list)

        def group_of(t: dict, pk: str) -> str:
            """The identity records are grouped under before chains are compared: the raw USR, except that a typedef's
            USR carries the file of whichever declaration a TU saw FIRST (`c:avio_internal.h@T@AVFormatContext` vs
            `c:avformat.h@T@AVFormatContext` for one redeclared typedef), so typedefs group by name and the chains
            decide, exactly as a tag's canonical declaration is settled."""
            u = t.get("usr") or pk
            return _TYPEDEF_FILE.sub("c:@T@", u) if t.get("kind") == "typedef" else u

        for s in summaries:
            for pk, t in s["types"].items():
                recs[(s["file"], pk)] = t
                by_usr[group_of(t, pk)].append((s["file"], pk))
        rekey: dict[tuple[str, str], str] = {}
        notes: list[str] = []

        def label(t: dict, usr: str) -> str:
            return f"{t.get('kind', 'type')} {t.get('qualname') or t.get('name') or usr}"

        def target_identity(tu: str, t: dict):
            """What a typedef definition names, as (target group, spelling): two redeclarations agree when these do."""
            tgt = recs.get((tu, t.get("underlying_usr") or ""))
            return (group_of(tgt, t["underlying_usr"]) if tgt else None, t.get("underlying") or "")

        # tags first, typedefs after them: a redeclared typedef merges only when its targets name one identity
        for usr, members in sorted(by_usr.items(), key=lambda kv: (recs[kv[1][0]].get("kind") == "typedef", kv[0])):
            parent = {m: m for m in members}

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            seen_file: dict[str, tuple[str, str]] = {}
            for m in members:
                for f in recs[m].get("chain") or []:
                    if f in seen_file:
                        a, b = find(m), find(seen_file[f])
                        if a != b:
                            parent[a] = b
                    else:
                        seen_file[f] = m
            classes: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
            for m in members:
                classes[find(m)].append(m)
            for cls in classes.values():
                defs = sorted({recs[m]["definition_file"] for m in cls if recs[m].get("definition_file")})
                if len(defs) == 1:
                    for m in cls:
                        rekey[m] = f"{usr}@{defs[0]}"
                elif not defs:
                    # a declaration-only class is keyed by the file EVERY member TU saw (the shared header that
                    # links two opaque declarations), else by the first declaring file in path order
                    chains = [set(recs[m].get("chain") or [m[1].rpartition("@")[2]]) for m in cls]
                    common = set.intersection(*chains)
                    first = min(common) if common else min(f for ch in chains for f in ch)
                    for m in cls:
                        rekey[m] = f"{usr}@{first}"
                elif recs[cls[0]].get("kind") == "typedef" and \
                        len({target_identity(m[0], recs[m]) for m in cls if recs[m].get("definition_file")}) == 1:
                    # a typedef redeclared in several headers (C requires redeclarations to name one type, and these
                    # do): one class, keyed by the declaring file every member TU saw, else the first in path order
                    chains = [set(recs[m].get("chain") or []) for m in cls]
                    common = set.intersection(*chains) & set(defs)
                    first = min(common) if common else defs[0]
                    for m in cls:
                        rekey[m] = f"{usr}@{first}"
                else:
                    for m in cls:
                        t = recs[m]
                        rekey[m] = f"{usr}@{t['definition_file']}" if t.get("definition_file") else m[1]
                    stubs = sorted({m[1].rpartition("@")[2] for m in cls if not recs[m].get("definition_file")})
                    if stubs:
                        t0 = recs[cls[0]]
                        notes.append(f"{label(t0, usr)}: declared in {', '.join(_ids.rel(f, self.root) for f in stubs)} but defined "
                                     f"differently in {', '.join(_ids.rel(f, self.root) for f in defs)}; the declaration is kept incomplete")
        # ---- variants by fingerprint
        tu_views: dict[str, dict[str, dict]] = defaultdict(dict)
        class_of: dict[int, str] = {}                    # id(record) -> its class key (records are distinct objects)
        for (tu, pk), t in recs.items():
            tu_views[tu][rekey[(tu, pk)]] = t
            class_of[id(t)] = rekey[(tu, pk)]
        usr_of: dict[str, str] = {}                      # class key -> raw usr
        ident_of: dict[str, list] = {}                   # class key -> stable (kind, qualname) from any record
        for tu, view in tu_views.items():
            for k, t in view.items():
                usr_of.setdefault(k, t.get("usr") or k.rpartition("@")[0])
                ident_of.setdefault(k, [t.get("kind"), t.get("qualname") or t.get("name") or ""])

        def stub_view(k: str) -> dict:
            """A declaration-only view (review rounds 10-11): the stable qualified identity plus the RECONCILED class's
            file — never the raw USR (a function-local type's USR carries a byte offset, so a comment above it would
            re-hash every dependent) and never the identity alone (two disconnected `struct x;` are two identities).
            A class no TU recorded falls back to its USR with the offset segments stripped."""
            ident = ident_of.get(k) or ["?", _USR_OFFSETS.sub("", usr_of.get(k) or k.rpartition("@")[0])]
            return {"identity": ["incomplete", *ident, _ids.rel(k.rpartition("@")[2], self.root)], "local": ["incomplete"], "edges": []}

        def view_rec(tu: str, t: dict) -> dict:
            if t.get("incomplete"):
                return stub_view(class_of[id(t)])

            def rk(x):
                return rekey.get((tu, x), x) if x else x
            # the identity's file is the RECONCILED class's (a typedef redeclared in two headers is one typedef
            # whatever header a TU happened to read first), never the record's own declaration file
            ident = [t.get("kind"), t.get("qualname") or t.get("name") or "",
                     _ids.rel(class_of[id(t)].rpartition("@")[2] or t.get("definition_file") or (t.get("loc") or {}).get("file") or "", self.root)]
            alias = t.get("kind") == "typedef"
            # a typedef's size/align belong to its target (unknown in a TU that only saw a forward declaration);
            # the target's fingerprint comes through the "u" edge, so the alias itself carries only its spelling
            local = [None if alias else t.get("size"), None if alias else t.get("align"), t.get("underlying") or "",
                     [[e.get("name"), e.get("value")] for e in t.get("enumerators") or []],
                     [[fl.get("name"), fl.get("type"), fl.get("offset"), fl.get("size"), fl.get("bit_offset"), fl.get("bit_width")]
                      for fl in t.get("fields") or []]]
            edges = [[f"f:{fl.get('name')}", rk(fl["type_usr"])] for fl in t.get("fields") or [] if fl.get("type_usr")]
            if t.get("underlying_usr"):
                edges.append(["u", rk(t["underlying_usr"])])
            return {"identity": ident, "local": local, "edges": edges}

        views: dict[tuple[str, str], dict] = {}
        complete: dict[str, list[dict]] = defaultdict(list)
        for tu, view in tu_views.items():
            for k, t in view.items():
                v = view_rec(tu, t)
                views[(tu, k)] = v
                if not t.get("incomplete"):
                    complete[k].append(v)
        # The unique complete view of a CLASS: all its complete views equal (local shape and edge keys). A TU that
        # only saw a declaration of that same class borrows it for FINGERPRINTING only, so dependents do not split
        # by what a TU happened to know. Never across classes (review round 9): a definition whose declaration
        # chain never met the stub is unrelated evidence, and substituting it would make hashes depend on TUs that
        # have nothing to do with the type.
        unique: dict[str, dict] = {k: vrs[0] for k, vrs in complete.items() if vrs and all(v == vrs[0] for v in vrs[1:])}
        stub_classes = {k for k in usr_of if k not in complete}
        self._stub_targets: dict[tuple[str, str], int] = {}
        fp: dict[tuple[str, str], str] = {}
        for tu, view in tu_views.items():
            inp: dict[str, dict] = {}
            for k, t in view.items():
                b = unique.get(k) if t.get("incomplete") else None
                inp[k] = b if b is not None else views[(tu, k)]
                self._stub_targets[(tu, k)] = sum(1 for _, tg in views[(tu, k)]["edges"] if tg in stub_classes)
            pending = [tg for r in list(inp.values()) for _, tg in r["edges"] if tg not in inp]
            while pending:
                tg = pending.pop()
                if tg in inp:
                    continue
                b = unique.get(tg)
                if b is not None:
                    inp[tg] = b
                    pending += [x for _, x in b["edges"] if x not in inp]
                else:
                    own = views.get((tu, tg))
                    inp[tg] = own if own is not None else stub_view(tg)
            res = _ids.fingerprint_types(inp)
            for k in view:
                fp[(tu, k)] = res[k]
        variants: dict[str, set[str]] = defaultdict(set)
        for (tu, k), h in fp.items():
            if not tu_views[tu][k].get("incomplete") or k in unique:
                variants[k].add(h)
        for (tu, pk), k in list(rekey.items()):
            if len(variants.get(k, ())) > 1 and (not recs[(tu, pk)].get("incomplete") or k in unique):
                rekey[(tu, pk)] = f"{k}|{fp[(tu, k)]}"
                self._stub_targets[(tu, rekey[(tu, pk)])] = self._stub_targets.get((tu, k), 0)
        for k, hs in sorted(variants.items()):
            if len(hs) > 1:
                t0 = next(tu_views[tu][k] for tu in tu_views if k in tu_views[tu])
                notes.append(f"{label(t0, k)}: {len(hs)} different layouts/targets across translation units (ids carry @<hash>)")
        self._type_notes = notes
        return rekey

    def _merge(self, summaries: list[dict]) -> None:
        """Fold per-TU summaries into one index. The result must not depend on which TUs came from the cache, so
        summaries are merged in (real) TU-path order and, for a function seen in several TUs (inline /
        header-defined), the TU that *is* the defining file wins, else the first TU in that order. Type keys are
        reconciled first (`_reconcile_types`) and every type reference is rewritten through the per-TU map."""
        summaries = sorted(summaries, key=lambda x: os.path.normcase(_ids.realpath(x["file"])))
        rekey = self._reconcile_types(summaries)
        owner: dict[str, str] = {}                       # key -> TU file whose summary we kept
        shapes: dict[str, dict[tuple, list[str]]] = {}   # key -> {(body_hash, callees): [TU files]}

        def shape(f: dict) -> tuple:
            return (f.get("body_hash"), tuple(c.get("callee_usr") or c.get("name") for c in f["callsites"]))

        for s in summaries:
            lang = s["lang"]
            tu = s["file"]

            def rk(k, _tu=tu):
                return rekey.get((_tu, k), k) if k else k

            for usr, f in s["functions"].items():
                f = dict(f)
                f["lang"] = lang
                f["params"] = [dict(p, type_usr=rk(p.get("type_usr"))) for p in f["params"]]
                f["returns"] = dict(f["returns"], type_usr=rk(f["returns"].get("type_usr")))
                f["type_usrs"] = _uniq([rk(k) for k in f["type_usrs"]])
                shapes.setdefault(usr, {}).setdefault(shape(f), []).append(tu)
                prev = self.functions.get(usr)
                if prev is not None:
                    if not (self._same_file(tu, f["loc"]["file"]) and not self._same_file(owner[usr], prev["loc"]["file"])):
                        continue                           # keep the earlier one unless this TU owns the definition
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
                    v["type_usr"] = rk(v.get("type_usr"))
                    self.vars[usr] = v
            for pk, t in s["types"].items():
                k = rk(pk)
                t = dict(t)
                t["lang"] = lang
                kfile = k.split("|")[0].rpartition("@")[2]
                if (t.get("incomplete") or t.get("kind") == "typedef") and kfile and (t.get("mentions") or {}).get(kfile) \
                        and not self._same_file(kfile, (t.get("loc") or {}).get("file")):
                    line, col = t["mentions"][kfile]                   # a class keyed by the file every TU saw (shared
                    t["loc"] = {"file": kfile, "line": line, "col": col}   # header, redeclared typedef): id and loc name it
                t["fields"] = [dict(fl, type_usr=rk(fl.get("type_usr"))) for fl in t.get("fields", [])]
                t["field_usrs"] = _uniq([rk(x) for x in t.get("field_usrs", [])])
                t["underlying_usr"] = rk(t.get("underlying_usr"))
                t["_stub_targets"] = getattr(self, "_stub_targets", {}).get((tu, k), 0)
                prev = self.types.get(k)
                if prev is None or (not prev.get("fields") and t.get("fields")) or (prev.get("incomplete") and not t.get("incomplete")) \
                        or (prev.get("size") is None and t.get("size") is not None) \
                        or (prev.get("incomplete") == t.get("incomplete") and bool(prev.get("fields")) == bool(t.get("fields"))
                            and t["_stub_targets"] < prev.get("_stub_targets", 0)):
                    self.types[k] = t                      # the most complete view of the type wins, whatever the TU order
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
        self.notes.extend(getattr(self, "_type_notes", []))
        # callers index
        for usr, f in self.functions.items():
            for cs in f["callsites"]:
                if cs.get("callee_usr"):
                    self.callers_idx.setdefault(cs["callee_usr"], []).append((usr, cs))
        # stable ids. C++ functions always carry their parameter type list (overloads), so an id never changes
        # because a sibling overload appeared; a #hash is added only on a residual collision (CVA6 review finding H5).
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
        cand_t: dict[str, str] = {}
        for key, t in self.types.items():
            relp = _ids.rel(t["loc"]["file"], self.root) if t.get("loc") else "?"
            line = t["loc"]["line"] if t.get("loc") else None
            if t["anonymous"] and t.get("qualname"):
                tid = _ids.type_id(t["lang"], relp, t["kind"], t["qualname"])   # e.g. "union dma_chan.stat"
            else:
                tid = _ids.type_id(t["lang"], relp, t["kind"], t.get("qualname") or t["name"],
                                   anonymous=t["anonymous"], line=line)
            if "|" in key:                                                   # a variant: fingerprint suffix (hx/2 form)
                tid += "@" + key.rpartition("|")[2]
            cand_t[key] = tid
        by_tid: dict[str, list[str]] = {}
        for key, tid in cand_t.items():
            by_tid.setdefault(tid, []).append(key)
        for tid, keys in by_tid.items():
            if len(keys) == 1:
                self.type_ids[keys[0]] = tid
                continue
            # two distinct types would share one id (the same tag in two blocks of one function, two anonymous
            # types on one line): a position-dependent #hash keeps both instead of silently dropping one
            for key in keys:
                t = self.types[key]
                relp = _ids.rel(t["loc"]["file"], self.root) if t.get("loc") else "?"
                self.type_ids[key] = f"{tid}#{_ids.short_hash(relp + '|' + (t.get('usr') or key))}"
            self.notes.append(f"{tid}: {len(keys)} distinct types share this id (position-dependent #hash added)")

    # ------------------------------------------------------------- Frontend API
    def _mkloc(self, d: Optional[dict]) -> Optional[Loc]:
        if not d:
            return None
        return Loc(file=_ids.rel(d["file"], self.root), line=d["line"], end_line=d.get("end_line"), col=d.get("col"))

    def locate_entry(self, file: str, symbol: str) -> str:
        abs_file = _ids.realpath(file if os.path.isabs(file) else os.path.join(self.root, file))
        if not os.path.exists(abs_file) and os.path.exists(_ids.realpath(file)):
            abs_file = _ids.realpath(file)

        def same(a: Optional[str]) -> bool:
            return bool(a) and os.path.normcase(_ids.realpath(a)) == os.path.normcase(abs_file)

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
