"""Call-site arguments of macro-expanded calls (review findings C2 and C3) and the cache key version."""
import json
import os
import shutil

from hx import __version__


def _macro_project(tmp_path):
    src = os.path.join(os.path.dirname(__file__), "fixtures", "c_macros")
    proj = tmp_path / "macros"
    shutil.copytree(src, proj, ignore=shutil.ignore_patterns(".hx", "__pycache__"))
    (proj / "build").mkdir()
    cc = [{"directory": str(proj), "file": f"src/{f}", "command": f"gcc -Iinclude -c src/{f} -o build/{f}.o"}
          for f in ("m.c", "impl.c")]
    (proj / "build" / "compile_commands.json").write_text(json.dumps(cc))
    return proj


def test_macro_call_arguments_follow_the_source(tmp_path):
    """The rule: a macro that WRAPS a call (or nests one in its expansion) contributes its own arguments, read from
    the recorded invocation span; a macro that GENERATES the callee name contributes the list that follows it.
    Literals are never split or re-spaced."""
    from hx.api import extract as _extract
    proj = _macro_project(tmp_path)
    g = _extract("src/m.c:use_macros", root=str(proj), depth=1, jobs=1)
    assert g.meta["index"]["tu_errors"] == 0, g.meta
    by: dict[str, list] = {}
    for e in g.edges:
        by.setdefault((e.dst or "").split("::")[-1], []).append(e)

    def args(name):
        return sorted(tuple(e.args) for e in by[name])

    assert args("logf_") == [("NULL", '"a, b"', "1"), ("NULL", '"x   y"'), ("NULL", '"z"', "2")]   # literals kept; alias resolved
    assert sorted(e.macro for e in by["logf_"]) == ["ALIAS", "LOG", "LOG"]
    assert args("fail_") == [("len <= left_(pb)",)]                                 # wrapper macro: its own argument
    assert args("left_") == [("len <= left_(pb)",)]                                 # a call inside that argument: same
    (sample,) = by["sample_impl"]
    assert sample.kind == "macro" and sample.macro == "FN" and sample.args == ["buf", "0"]   # name-generating macro
    assert args("store32_") == [("dst", "n")] and args("bswap_") == [("dst", "n")]           # nested in the expansion
    assert all(e.macro == "WB32" for e in by["store32_"] + by["bswap_"])
    plain_edges = sorted(by["plain"], key=lambda e: e.loc.line)
    assert [(e.kind, e.macro, e.args) for e in plain_edges] == [("macro", "PICK", ["len", "", "2"]),   # empty argument kept
                                                                ("call", None, ["len", "0"])]           # ordinary call across two lines


def test_literal_whitespace_edit_changes_edge_args(tmp_path):
    """Review finding C3: three spaces -> four spaces inside a literal must show up in the edge arguments, not only in
    the body hash."""
    from hx.api import extract as _extract
    from hx.diff import diff_graphs
    proj = _macro_project(tmp_path)
    before = _extract("src/m.c:use_macros", root=str(proj), depth=1, jobs=1)
    m_c = proj / "src" / "m.c"
    m_c.write_text(m_c.read_text().replace('"x   y"', '"x    y"', 1))
    after = _extract("src/m.c:use_macros", root=str(proj), depth=1, jobs=1)
    la = [e for e in before.edges if (e.dst or "").endswith("::logf_") and e.args[1].startswith('"x')]
    lb = [e for e in after.edges if (e.dst or "").endswith("::logf_") and e.args[1].startswith('"x')]
    assert la[0].args == ["NULL", '"x   y"'] and lb[0].args == ["NULL", '"x    y"']
    d = diff_graphs(before.to_dict(), after.to_dict())
    assert d["summary"]["edges_args_changed"] >= 1, d["summary"]


def test_cache_extra_pins_summary_version(cproj):
    from hx.frontends.clang_fe import ClangFrontend, SUMMARY_VERSION
    fe = ClangFrontend(str(cproj), str(cproj / "build"))
    extra = fe._cache_extra()
    assert extra[0] == SUMMARY_VERSION == 5
    assert __version__ in extra and isinstance(extra[4], str)      # hx and libclang versions are part of the key
