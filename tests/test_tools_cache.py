"""The optional-tool registry's resolution order and the cache's missing-file sentinel, both without any vendor tool."""
import dataclasses
import os
import stat

import pytest

from hx.cache import TUCache
from hx.frontends.base import FrontendError
from hx.tools import TOOLS, find_tool, resolve_tool


def _exe(path):
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_tool_resolution_order_override_env_path_fallback(tmp_path, monkeypatch):
    empty = tmp_path / "bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))                                            # nothing on PATH
    fallback = _exe(tmp_path / "fallback" / "Xyce") if (tmp_path / "fallback").mkdir() is None else None
    monkeypatch.setitem(TOOLS, "xyce", dataclasses.replace(TOOLS["xyce"], fallbacks=(fallback,)))
    monkeypatch.delenv("HX_TOOL_XYCE", raising=False)
    assert find_tool("xyce") == fallback                                               # last resort: the known location
    env_exe = _exe(tmp_path / "env" / "Xyce") if (tmp_path / "env").mkdir() is None else None
    monkeypatch.setenv("HX_TOOL_XYCE", env_exe)
    assert find_tool("xyce") == env_exe                                                # the environment wins over fallbacks
    monkeypatch.setenv("HX_TOOL_XYCE", str(tmp_path / "nope" / "Xyce"))
    assert find_tool("xyce") == fallback                                               # a dangling variable is ignored
    on_path = _exe(empty / "Xyce")
    assert find_tool("xyce") == on_path                                                # PATH beats fallbacks
    assert find_tool("xyce", override=str(tmp_path / "missing" / "Xyce")) is None     # an explicit path never falls back
    with pytest.raises(FrontendError) as ei:
        resolve_tool("xyce", str(tmp_path / "missing" / "Xyce"))
    assert "Xyce executable" in str(ei.value) and "missing/Xyce" in str(ei.value) and "--xyce PATH" in str(ei.value)
    assert resolve_tool("xyce", on_path) == on_path and resolve_tool("xyce", "Xyce") == on_path


def test_cache_missing_file_sentinel(tmp_path):
    present = tmp_path / "a.inc"
    present.write_text("x")
    deps = {str(present): present.stat().st_mtime_ns, str(tmp_path / "later.inc"): None}
    assert TUCache.deps_fresh(deps)
    (tmp_path / "later.inc").write_text("now it exists")                                 # a candidate that appeared invalidates
    assert not TUCache.deps_fresh(deps)
    assert not TUCache.deps_fresh({str(tmp_path / "gone.inc"): 123})                     # a dep that vanished invalidates
    os.utime(present, (1, 1))
    assert not TUCache.deps_fresh({str(present): deps[str(present)]})                    # and so does a new mtime
