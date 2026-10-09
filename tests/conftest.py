import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURE_C = Path(__file__).parent / "fixtures" / "c"


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
    shutil.copytree(FIXTURE_C, dst)
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
