"""Oracle failure paths with FAKE simulators: every branch of `compare`, `check_ngspice` and `check_external` that a live
agreement run can never reach (mismatches, rejection, garbage output, timeouts, XDM translation loss) runs here without
ngspice, Xyce or XDM installed."""
import json
import os
import shutil
import stat
import sys

import pytest

from hx.cli import main
from hx.netlist import oracle
from hx.netlist.check import check_ngspice, format_report
from hx.netlist.profiles import NGSPICE, SPICE_FAMILIES
from hx.netlist.xyce import check_external

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _fake(tmp_path, name, body):
    """An executable Python script standing in for a simulator."""
    p = tmp_path / name
    p.write_text(f"#!{sys.executable}\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(p)


def _dev(name, letter, terminals, segments=(), flags=(), model=None, prefix=None, refs=(), guarded=False):
    return oracle.HxDevice(node_id="sp:x::" + name, letter=letter, name=name, segments=list(segments), local_flags=list(flags),
                           guarded=guarded, terminals=list(terminals), model=model, model_scope_prefix=prefix, refs=list(refs),
                           family=SPICE_FAMILIES[letter])


# ------------------------------------------------------------------ compare: the branches live runs never produce
def test_compare_reports_a_wrong_net():
    lst = oracle.parse_listing("     1 : t\n     2 : r1 n1 n3 1k\n")
    res = oracle.compare([_dev("r1", "R", ["n1", "n2"])], lst, NGSPICE, set())
    assert res["mismatches"] == [{"path": "r1", "what": "net", "terminal": 1, "hx": "n2", "ngspice": "n3"}]
    assert res["summary"]["compared"] == 1 and not res["summary"]["agree"]


def test_compare_tolerant_name_form_is_reported_not_silent():
    lst = oracle.parse_listing("     1 : t\n     2 : r.x1.r.r1 n1 0 1k\n")               # hx expects r.x1.r1 (global definition)
    res = oracle.compare([_dev("r1", "R", ["n1", "0"], ["x1"], [False])], lst, NGSPICE, set())
    assert [m["what"] for m in res["mismatches"]] == ["name-form"]
    assert res["mismatches"][0]["hx"] == "r.x1.r1" and res["mismatches"][0]["ngspice"] == "r.x1.r.r1"
    assert res["summary"]["name_form"] == 1 and res["summary"]["compared"] == 1 and res["summary"]["unmatched"] == 0


def test_compare_reports_devices_missing_on_either_side():
    lst = oracle.parse_listing("     1 : t\n     2 : r1 n1 0 1k\n     3 : rz n1 0 1k\n")
    res = oracle.compare([_dev("r1", "R", ["n1", "0"]), _dev("rt", "R", ["n1", "0"])], lst, NGSPICE, set())
    kinds = sorted((m["what"], m["path"]) for m in res["mismatches"])
    assert kinds == [("missing-in-hx", "rz"), ("missing-in-ngspice", "rt")] and res["summary"]["unmatched"] == 2


def test_compare_reports_a_different_model_name_and_a_reference_count():
    lst = oracle.parse_listing("     1 : t\n     2 : d1 n1 0 dx\n     3 : k1 l1\n     4 : .model dx d is=1\n")
    res = oracle.compare([_dev("d1", "D", ["n1", "0"], model="dm", prefix=""), _dev("k1", "K", [], refs=["l1", "l2"])], lst, NGSPICE, {"dm"})
    whats = [(m["what"], m["path"], m["hx"], m["ngspice"]) for m in res["mismatches"]]
    assert ("model", "d1", "dm", "dx") in whats                                       # base name differs, not only the scope prefix
    assert ("ref", "k1", 2, 1) in whats                                                # one coupled inductor listed, hx has two


# ------------------------------------------------------------------ fake ngspice through check_ngspice and the CLI
_DECK = """fake deck
.subckt leaf a b
r1 a b 1k
.ends
x1 n1 0 leaf
x2 n1 0 leaf
rt n1 n2 1k
c1 n2 0 1p
.end
"""
_GOOD_ROWS = ["     1 : fake deck", "     3 : r.x1.r1 n1 0 1k", "     3 : r.x2.r1 n1 0 1k", "     7 : rt n1 n2 1k", "     8 : c1 n2 0 1p"]


def _listing_fake(tmp_path, rows, exit_code=0, stderr=""):
    body = "import sys\nsys.stdin.read()\n" + f"sys.stderr.write({stderr!r})\n" + "".join(f"print({r!r})\n" for r in rows) + f"sys.exit({exit_code})\n"
    return _fake(tmp_path, "ngspice-fake", body)


def _deck(tmp_path, text=_DECK, name="fake.sp"):
    root = tmp_path / "deck"
    root.mkdir(exist_ok=True)
    (root / name).write_text(text)
    return root


def test_fake_ngspice_agreement_and_scopes(tmp_path):
    root = _deck(tmp_path)
    exe = _listing_fake(tmp_path, _GOOD_ROWS)
    rep = check_ngspice("fake.sp:.", root=str(root), exe=exe)
    assert rep["status"] == "agree" and rep["scope"] == "whole deck" and rep["summary"]["compared"] == 4
    rep = check_ngspice("fake.sp:x1", root=str(root), exe=exe)
    assert rep["status"] == "agree" and rep["scope"] == "instance x1" and rep["summary"]["compared"] == 1 and rep["summary"]["out_of_scope"] == 3
    rep = check_ngspice("fake.sp:x1.r1", root=str(root), exe=exe)
    assert rep["scope"] == "device x1.r1 (its enclosing instance x1)" and rep["summary"]["compared"] == 1
    rep = check_ngspice("fake.sp:@leaf", root=str(root), exe=exe)
    assert rep["status"] == "agree" and rep["scope"].startswith("definition leaf per unguarded instance in deck fake.sp") and rep["summary"]["instances"] == 2
    text = format_report(rep)
    assert "scope       definition leaf per unguarded instance" in text and "dialect     spice" in text and "instance    x1: compared 1, mismatches 0" in text


def test_fake_ngspice_mismatch_is_exit_1_with_scope_in_the_text_report(tmp_path, capsys):
    root = _deck(tmp_path)
    rows = list(_GOOD_ROWS)
    rows[3] = "     7 : rt n1 n3 1k"                                                     # a wrong net on rt
    exe = _listing_fake(tmp_path, rows)
    assert main(["netlist", "check", "fake.sp:.", "--ngspice", exe, "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "status      mismatch" in out and "scope       whole deck" in out and "mismatch    net                rt [1]: hx 'n2' vs ngspice 'n3'" in out
    # the instance subtree does not see the top-level mismatch
    assert main(["netlist", "check", "fake.sp:x2", "--ngspice", exe, "--root", str(root), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["status"] == "agree" and rep["scope"] == "instance x2"


def test_fake_ngspice_failure_garbage_and_timeout_are_unavailable(tmp_path, capsys):
    root = _deck(tmp_path)
    failing = _listing_fake(tmp_path, [], exit_code=1, stderr="Error on line 7 : undefined parameter [x]\nngspice exited\n")
    rep = check_ngspice("fake.sp:.", root=str(root), exe=failing)
    assert rep["status"] == "unavailable" and rep["reason"].startswith("oracle unavailable: ngspice exit 1: Error on line 7 : undefined parameter [x]")
    assert rep["scope"] == "whole deck" and rep["render"] and rep["summary"] is None
    assert main(["netlist", "check", "fake.sp:.", "--ngspice", failing, "--root", str(root)]) == 2
    assert "reason      oracle unavailable: ngspice exit 1" in capsys.readouterr().out
    garbage = _listing_fake(tmp_path, ["hello world"])                                 # exit 0, no listing at all
    rep = check_ngspice("fake.sp:.", root=str(root), exe=garbage)
    assert rep["status"] == "unavailable" and rep["reason"] == "oracle unavailable: ngspice exit 0: (no stderr)"
    sleeper = _fake(tmp_path, "ngspice-sleep", "import sys, time\nsys.stdin.read()\ntime.sleep(5)\n")
    rep = check_ngspice("fake.sp:.", root=str(root), exe=sleeper, timeout=0.3)
    assert rep["status"] == "unavailable" and rep["reason"] == "oracle unavailable: ngspice timed out after 0.3s"
    assert main(["netlist", "check", "fake.sp:.", "--ngspice", sleeper, "--root", str(root), "--timeout", "0.3"]) == 2


# ------------------------------------------------------------------ fake Xyce
_XDECK = """fake xyce deck
R1 n1 n2 1k
C1 n2 0 1p
D1 n1 0 dm
.subckt leaf a b
R2 a b 2k
.ends
X1 n1 n2 leaf
.model dm D
.end
"""
_FAKE_XYCE = r'''
import os, sys, time
mode = os.environ.get("FAKE_XYCE_MODE", "agree")
args = sys.argv[1:]
if mode == "sleep":
    time.sleep(5)
if args[0] == "-syntax":
    if mode == "reject":
        print("Netlist error: unknown device"); sys.exit(1)
    counts = {"R": 2, "C": 1, "D": 1}
    if mode == "family":
        counts["R"] = 3
    print("***** Device Count Summary")
    for k, v in counts.items():
        print(f"       {k}       {v}")
    sys.exit(0)
if args[0] == "-norun":
    if mode == "topo":
        print("Xyce cannot elaborate the topology"); sys.exit(1)
    names = args[args.index("-namesfile") + 1]
    nets = ["n1", "n2"] if mode != "net" else ["n1"]
    with open(names, "w") as fh:
        fh.write("".join(f"{i} {n}\n" for i, n in enumerate(nets, 1)))
    sys.exit(0)
sys.exit(3)
'''


def _xdeck(tmp_path, text=_XDECK, name="xdeck.cir"):
    root = tmp_path / "xroot"
    root.mkdir(exist_ok=True)
    (root / name).write_text(text)
    return root


def test_fake_xyce_agreement_scope_and_dialect(tmp_path, monkeypatch, capsys):
    root = _xdeck(tmp_path)
    exe = _fake(tmp_path, "Xyce-fake", _FAKE_XYCE)
    rep = check_external("xdeck.cir:.", root=str(root), oracle="xyce", exe=exe)
    assert rep["status"] == "agree" and rep["checked"] == ["original-deck syntax", "device-family counts", "topology acceptance", "exposed net names"]
    assert rep["summary"]["hx_families"] == {"R": 2, "C": 1, "D": 1} and rep["scope"] == "whole deck" and rep["dialect"] == "xyce"
    # a definition entry with deck context is checked as the whole deck; an explicit dialect is kept
    rep = check_external("xdeck.cir:@leaf", root=str(root), oracle="xyce", exe=exe, deck="xdeck.cir", dialect="xyce")
    assert rep["status"] == "agree" and rep["scope"] == "whole deck"
    assert main(["netlist", "check", "xdeck.cir:x1", "--oracle", "xyce", "--xyce", exe, "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "scope       whole deck" in out and "dialect     xyce" in out and "checked     original-deck syntax" in out


def test_fake_xyce_failure_branches(tmp_path, monkeypatch):
    root = _xdeck(tmp_path)
    exe = _fake(tmp_path, "Xyce-fake", _FAKE_XYCE)
    monkeypatch.setenv("FAKE_XYCE_MODE", "reject")
    rep = check_external("xdeck.cir:.", root=str(root), oracle="xyce", exe=exe)
    assert rep["status"] == "unavailable" and rep["reason"].startswith("Xyce rejected the deck (exit 1)") and "unknown device" in rep["stdout"]
    monkeypatch.setenv("FAKE_XYCE_MODE", "family")
    rep = check_external("xdeck.cir:.", root=str(root), oracle="xyce", exe=exe)
    assert rep["status"] == "mismatch" and rep["mismatches"] == [{"what": "family count", "path": "R", "hx": 2, "oracle": 3}]
    monkeypatch.setenv("FAKE_XYCE_MODE", "net")
    rep = check_external("xdeck.cir:.", root=str(root), oracle="xyce", exe=exe)
    assert rep["status"] == "mismatch" and rep["mismatches"] == [{"what": "exposed net", "path": "n2", "hx": "n2", "oracle": None}]
    monkeypatch.setenv("FAKE_XYCE_MODE", "topo")
    rep = check_external("xdeck.cir:.", root=str(root), oracle="xyce", exe=exe)
    assert rep["status"] == "unavailable" and rep["reason"].startswith("Xyce topology/names unavailable") and "cannot elaborate" in rep["reason"]
    monkeypatch.setenv("FAKE_XYCE_MODE", "sleep")
    rep = check_external("xdeck.cir:.", root=str(root), oracle="xyce", exe=exe, timeout=0.3)
    assert rep["status"] == "unavailable" and rep["reason"] == "xyce timed out after 0.3s"
    monkeypatch.delenv("FAKE_XYCE_MODE")
    (root / "lib.inc").write_text(".subckt leaf2 a b\nR9 a b 1k\n.ends\n")
    rep = check_external("lib.inc:@leaf2", root=str(root), oracle="xyce", exe=exe)        # a standalone library: no deck context
    assert rep["status"] == "unavailable" and rep["reason"].startswith("no deck context")
    broken = tmp_path / "not-executable"
    broken.write_text("data")
    rep = check_external("xdeck.cir:.", root=str(root), oracle="xyce", exe=str(broken))
    assert rep["status"] == "unavailable" and rep["reason"].startswith("cannot execute xyce")


# ------------------------------------------------------------------ fake XDM
_FAKE_XDM = r'''
import os, sys
mode = os.environ.get("FAKE_XDM_MODE", "agree")
deck = sys.argv[-1]
base = os.path.basename(deck)
if mode == "warn":
    print("WARNING: ADC device translation is lossy"); sys.exit(0)
rows, depth = [], 0
for i, line in enumerate(open(deck), 1):
    t = line.strip()
    low = t.lower()
    if i == 1 or not t or t[0] in "*+":
        continue
    if low.startswith(".subckt"):
        depth += 1; continue
    if low.startswith(".ends"):
        depth -= 1; continue
    if t.startswith(".") or depth or low.startswith("x"):
        continue
    name = t.split()[0].lower()
    if name.startswith("y") and len(t.split()) > 1:
        name = "y" + t.split()[1].lower()
    rows.append((base, i, name))
if mode == "missing":
    rows = rows[1:]
if mode == "extra":
    rows.append((base, 99, "rghost"))
if mode == "nou":
    rows = [r for r in rows if not r[2].startswith("u")]
for b, i, n in rows:
    print(f"{b}, {i}, {n}, R, 2")
'''


def test_fake_xdm_inventory_agreement_and_mismatches(tmp_path, monkeypatch):
    root = _xdeck(tmp_path)
    exe = _fake(tmp_path, "xdm-fake", _FAKE_XDM)
    rep = check_external("xdeck.cir:.", root=str(root), oracle="xdm", exe=exe)
    assert rep["status"] == "agree" and rep["checked"] == ["XDM parse acceptance", "top-level primitive inventory"]
    assert rep["unverified"] == ["subcircuit inventory", "terminal bindings", "model values"] and rep["summary"] == {"hx_devices": 3, "oracle_devices": 3}
    monkeypatch.setenv("FAKE_XDM_MODE", "missing")
    rep = check_external("xdeck.cir:.", root=str(root), oracle="xdm", exe=exe)
    assert rep["status"] == "mismatch" and [(m["hx"], m["oracle"]) for m in rep["mismatches"]] == [(True, False)] and "'r1'" in rep["mismatches"][0]["path"]
    monkeypatch.setenv("FAKE_XDM_MODE", "extra")
    rep = check_external("xdeck.cir:.", root=str(root), oracle="xdm", exe=exe)
    assert rep["status"] == "mismatch" and [(m["hx"], m["oracle"]) for m in rep["mismatches"]] == [(False, True)] and "rghost" in rep["mismatches"][0]["path"]


def test_fake_xdm_translation_loss_missing_u_and_empty_inventory_are_unavailable(tmp_path, monkeypatch):
    root = _xdeck(tmp_path)
    exe = _fake(tmp_path, "xdm-fake", _FAKE_XDM)
    monkeypatch.setenv("FAKE_XDM_MODE", "warn")
    rep = check_external("xdeck.cir:.", root=str(root), oracle="xdm", exe=exe)
    assert rep["status"] == "unavailable" and rep["reason"].startswith("XDM coverage unavailable: WARNING: ADC device translation is lossy")
    shutil.copy(os.path.join(FIX, "xyce", "digital.cir"), root / "digital.cir")
    monkeypatch.setenv("FAKE_XDM_MODE", "nou")
    rep = check_external("digital.cir:.", root=str(root), oracle="xdm", exe=exe)
    assert rep["status"] == "unavailable" and rep["reason"].startswith("XDM query omits U digital devices") and "ugate" in rep["reason"]
    assert rep["unverified"][0] == "U digital devices"
    monkeypatch.delenv("FAKE_XDM_MODE")
    (root / "only_x.cir").write_text("only a subcircuit\n.subckt leaf a b\nR2 a b 2k\n.ends\nX1 n1 n2 leaf\n.end\n")
    rep = check_external("only_x.cir:.", root=str(root), oracle="xdm", exe=exe)
    assert rep["status"] == "unavailable" and rep["reason"] == "XDM query exposes no top-level primitives to compare"
