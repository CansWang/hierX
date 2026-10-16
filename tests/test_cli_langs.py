"""`hx extract` end to end for the Phase 3 languages (skipped when a toolchain is missing)."""
import json
import os
import shutil
import subprocess
import sys

import pytest

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
RA = shutil.which("rust-analyzer") or (os.path.expanduser("~/.cargo/bin/rust-analyzer") if os.path.exists(os.path.expanduser("~/.cargo/bin/rust-analyzer")) else None)


def run(args, cwd, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-m", "hx.cli", *args], cwd=cwd, capture_output=True, text=True, env=env)


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator missing")
def test_sv_cli(tmp_path):
    dst = tmp_path / "sv"
    shutil.copytree(os.path.join(FIX, "sv"), dst, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
    r = run(["extract", "rtl/top.sv:top", "--depth", "2", "-o", "out/g.json"], cwd=dst)
    assert r.returncode == 0, r.stderr
    assert "entry       sv:rtl/top.sv::top" in r.stdout
    g = json.load(open(dst / "out" / "g.json"))
    assert g["lang"] == "sv" and g["meta"]["extract_args"]["top"] is None and g["meta"]["extract_args"]["lang"] == "sv"   # verilator picked the top
    assert any(e["kind"] == "instance" for e in g["edges"])
    r = run(["extract", "rtl/core.sv:top.u_core_b.u_alu", "--include-callers", "--depth", "3", "-f", "files.f", "-o", "out/g2.json"], cwd=dst)
    assert r.returncode == 0, r.stderr
    g = json.load(open(dst / "out" / "g2.json"))
    assert g["entry"] == "sv:rtl/alu.sv::top.u_core_b.u_alu" and g["nodes"]["sv:rtl/top.sv::top"]["depth"] == -2 and g["meta"]["extract_args"]["top"] == "top"
    r = run(["extract", "rtl/top.sv:core", "-o", "out/g3.json"], cwd=dst)
    assert r.returncode == 2 and "instantiated 2 times" in r.stderr and "top.u_core_a" in r.stderr


@pytest.mark.skipif(RA is None, reason="rust-analyzer missing")
def test_rust_cli(tmp_path):
    dst = tmp_path / "rust"
    shutil.copytree(os.path.join(FIX, "rust"), dst, ignore=shutil.ignore_patterns("target"))
    r = run(["extract", "src/lib.rs:app_run", "--depth", "2", "--lsp-cmd", RA, "-o", "out/g.json"], cwd=dst)
    assert r.returncode == 0, r.stderr
    assert "server      " in r.stdout and "precision lsp" in r.stdout
    g = json.load(open(dst / "out" / "g.json"))
    assert g["lang"] == "rs" and "rs:src/dma.rs::dma_start" in g["nodes"]
    assert g["meta"]["extract_args"]["lsp_cmd"] == [RA]
    assert all(n["precision"] == "lsp" for n in g["nodes"].values())


@pytest.mark.skipif(shutil.which("pyright-langserver") is None, reason="pyright missing")
def test_python_cli(tmp_path):
    dst = tmp_path / "python"
    shutil.copytree(os.path.join(FIX, "python"), dst, ignore=shutil.ignore_patterns(".hx", "__pycache__", "obj_dir"))
    r = run(["extract", "hxfix/main.py:app_run", "--depth", "1", "-o", "out/g.json"], cwd=dst)
    assert r.returncode == 0, r.stderr
    g = json.load(open(dst / "out" / "g.json"))
    assert g["lang"] == "py" and set(n.split("::")[1] for n in g["nodes"]) == {"app_run", "dma_start", "dma_poll"}
    r = run(["extract", "hxfix/main.py:app_run", "--lang", "cobol"], cwd=dst)
    assert r.returncode == 2 and "not supported" in r.stderr


def test_unknown_extension_needs_lang(tmp_path):
    (tmp_path / "x.zig").write_text("fn f() void {}\n")
    r = run(["extract", "x.zig:f"], cwd=tmp_path)
    assert r.returncode == 2 and "cannot infer the language" in r.stderr


def test_spice_cli(tmp_path):
    dst = tmp_path / "spice"
    shutil.copytree(os.path.join(FIX, "spice", "ota"), dst, ignore=shutil.ignore_patterns(".hx"))
    r = run(["extract", "ota.sp:.", "--all", "--dialect", "ngspice", "-o", "out/g.json"], cwd=dst)
    assert r.returncode == 0, r.stderr
    assert "entry       sp:ota.sp::(deck) ota.sp" in r.stdout and "dialect ngspice" in r.stdout
    g = json.load(open(dst / "out" / "g.json"))
    assert g["lang"] == "sp" and g["meta"]["extract_args"]["dialect"] == "ngspice" and g["meta"]["extract_args"]["deck"] is None   # omitted stays omitted
    assert g["meta"]["index"]["deck"] == "ota.sp" and g["meta"]["index"]["deck_role"] == "deck"
    assert "circuit" in g and any(n["kind"] == "device" for n in g["nodes"].values()) and all(n["precision"] == "syntax" for n in g["nodes"].values())
    r = run(["extract", "ota.sp:xa.x_cm.xref", "--include-callers", "--depth", "3", "-o", "out/g2.json"], cwd=dst)
    assert r.returncode == 0, r.stderr
    g = json.load(open(dst / "out" / "g2.json"))
    assert g["entry"] == "sp:ota.sp::xa.x_cm.xref" and g["nodes"]["sp:ota.sp::(deck) ota.sp"]["depth"] == -3
    r = run(["extract", "lib/devices.inc:@cm", "--deck", "ota.sp", "-o", "out/g3.json"], cwd=dst)
    assert r.returncode == 0 and "sp:lib/devices.inc::@cm" in r.stdout, r.stderr
    r = run(["extract", "ota.sp:nope", "-o", "out/g4.json"], cwd=dst)
    assert r.returncode == 2 and "neither an instance path" in r.stderr
    r = run(["extract", "ota.sp:.", "--dialect", "spectre", "-o", "out/g5.json"], cwd=dst)
    assert r.returncode == 2 and "later phase" in r.stderr
    lib = tmp_path / "lib"
    shutil.copytree(os.path.join(FIX, "spice", "params"), lib, ignore=shutil.ignore_patterns(".hx"))
    r = run(["extract", "inc_first_subckt.inc:@leaf", "-o", "out/g6.json"], cwd=lib)            # a standalone library, no --deck
    assert r.returncode == 0 and "sp:inc_first_subckt.inc::@leaf" in r.stdout, r.stderr
    assert json.load(open(lib / "out" / "g6.json"))["meta"]["index"]["deck_role"] == "library"
