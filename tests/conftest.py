import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURE_C = Path(__file__).parent / "fixtures" / "c"
REQUIRE_TOOLS = bool(os.environ.get("HX_REQUIRE_TOOLS"))
# Vendor tools (Xyce, XDM, Spectre, HSPICE) are not apt-installable: their tests skip when the tool is absent unless
# HX_REQUIRE_VENDOR_TOOLS names the tool key (comma list) or says `all`.
_vendor = os.environ.get("HX_REQUIRE_VENDOR_TOOLS", "")
REQUIRED_VENDORS = {"ngspice", "xyce", "xdm", "spectre", "hspice"} if _vendor.strip() == "all" else {k.strip() for k in _vendor.split(",") if k.strip()}


def require_tool(name: str, *fallbacks: str) -> str:
    """Path of an external tool, or skip the test — unless HX_REQUIRE_TOOLS=1 (CI), where a missing tool FAILS.

    Optional toolchains must never make the suite look green by silently skipping."""
    p = shutil.which(name)
    for fb in fallbacks:
        if p:
            break
        fb = os.path.expanduser(fb)
        if os.path.exists(fb):
            p = fb
    if p:
        return p
    msg = f"{name} not installed"
    if REQUIRE_TOOLS:
        pytest.fail("HX_REQUIRE_TOOLS=1: " + msg)
    pytest.skip(msg)


def require_vendor_tool(key: str) -> str:
    """Path of an optional vendor tool through hx's registry; skip when absent unless HX_REQUIRE_VENDOR_TOOLS lists it."""
    from hx.tools import TOOLS, find_tool
    p = find_tool(key)
    if p:
        return p
    msg = f"{TOOLS[key].name} not installed ({TOOLS[key].install})"
    if key in REQUIRED_VENDORS:
        pytest.fail(f"HX_REQUIRE_VENDOR_TOOLS={_vendor}: " + msg)
    pytest.skip(msg)


def pytest_configure(config):
    config.addinivalue_line("markers", "vendor_tool(key): needs an optional vendor tool; its skip becomes a failure only when HX_REQUIRE_VENDOR_TOOLS lists the key")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """With HX_REQUIRE_TOOLS=1 every skip (markers, pytest.skip, importorskip) becomes a failure — except a test
    marked vendor_tool(key) whose key HX_REQUIRE_VENDOR_TOOLS does not list."""
    outcome = yield
    rep = outcome.get_result()
    if REQUIRE_TOOLS and rep.skipped:
        marker = item.get_closest_marker("vendor_tool")
        if marker and marker.args and marker.args[0] not in REQUIRED_VENDORS:
            return
        rep.outcome = "failed"
        rep.longrepr = f"HX_REQUIRE_TOOLS=1: skipped test treated as failure: {rep.longrepr}"


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    rep = outcome.get_result()
    if REQUIRE_TOOLS and rep.skipped:
        rep.outcome = "failed"
        rep.longrepr = f"HX_REQUIRE_TOOLS=1: skipped module treated as failure: {rep.longrepr}"


def write_compile_commands(proj: Path) -> Path:
    build = proj / "build"
    build.mkdir(exist_ok=True)
    entries = []
    for src in sorted((proj / "src").glob("*.c")):
        entries.append({
            "directory": str(proj),
            "command": f"gcc -Iinclude -Wall -O1 -c {src.relative_to(proj)} -o build/{src.stem}.o",
            "file": str(src.relative_to(proj)),
        })
    out = build / "compile_commands.json"
    out.write_text(json.dumps(entries, indent=1))
    return out


@pytest.fixture
def cproj(tmp_path) -> Path:
    dst = tmp_path / "cproj"
    shutil.copytree(FIXTURE_C, dst, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
    write_compile_commands(dst)
    return dst


@pytest.fixture
def extract(cproj):
    from hx.api import extract as _extract

    def run(entry="src/main.c:app_run", **kw):
        kw.setdefault("jobs", 1)
        return _extract(entry, root=str(cproj), **kw)
    return run


@pytest.fixture(scope="session")
def layout_probe(tmp_path_factory):
    """Ground truth from the real compiler: sizeof/offsetof of the fixture structs."""
    d = tmp_path_factory.mktemp("probe")
    probe = d / "probe.c"
    probe.write_text(r'''
#include <stdio.h>
#include <stddef.h>
#include "dma.h"
#define F(T, f) printf("\"%s\":%zu,", #f, offsetof(T, f))
int main(void) {
    printf("{\"struct dma_chan\":{\"size\":%zu,", sizeof(struct dma_chan));
    F(struct dma_chan, base); F(struct dma_chan, desc); F(struct dma_chan, cb); F(struct dma_chan, cb_ctx); F(struct dma_chan, stat); F(struct dma_chan, head);
    printf("\"_\":0},\"struct dma_desc\":{\"size\":%zu,", sizeof(struct dma_desc));
    F(struct dma_desc, src); F(struct dma_desc, dst); F(struct dma_desc, len); F(struct dma_desc, flags);
    printf("\"_\":0}}\n");
    return 0;
}
''')
    exe = d / "probe"
    subprocess.run(["gcc", "-I", str(FIXTURE_C / "include"), str(probe), "-o", str(exe)], check=True)
    return json.loads(subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout)
