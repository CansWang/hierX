#!/usr/bin/env python
"""Netlist coverage run (SSOT Phase N1): the apragma example decks and the sky130 library wrapper, extracted with hx,
with the ngspice oracle where a deck is numeric, and the acceptance thresholds evaluated.

    .venv/bin/python dev/scripts/netlist_coverage.py --out /home/canswang/hx-review-artifacts/netlists/<stamp>/

Writes coverage.json, coverage.md, graphs/*.json, commands.txt and the sky130 wrapper deck. The apragma checkout is
never written to: the example decks are copied into <out>/apragma-mirror (same relative paths) with `models` symlinked
to the checkout, so ids match an in-repo run and the cache lands under the mirror. Exit 1 when a threshold fails.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter

HX = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HX)

APRAGMA = os.environ.get("HX_APRAGMA", "/home/canswang/apragma")
EXAMPLES = [
    "evals/debug/ota_5t/generated/netlist.ngspice.sp",                                                  # symbolic template
    "evals/body_effect/spice_sim/vth_vs_vsb_ihp_sg13_lv.spi",                                           # IHP SG13 sweep
    "evals/sizing_err_benchmark/results/sim_runs/opamp_5t_gf180_SF_Tp27/sample_001/ota5t_gf180.spi",    # numeric GF180 sample
]
SYMBOLIC, NUMERIC = EXAMPLES[0], EXAMPLES[2]
SKY130_LIB = os.environ.get("HX_SKY130_LIB", os.path.join(APRAGMA, "models", "sky130", "models", "sky130.lib.spice"))
SKY130_DEF = "sky130_fd_pr__nfet_01v8"
THRESHOLDS = {"sky130_cold_seconds": 30.0, "sky130_warm_seconds": 3.0}


def stats(g: dict) -> dict:
    nodes, c = g["nodes"], g.get("circuit") or {}
    entry = nodes.get(g["entry"], {})
    return {
        "nodes": dict(Counter(n["kind"] for n in nodes.values())),
        "statements": entry.get("attrs", {}).get("statements"),
        "families": dict(Counter(n.get("attrs", {}).get("family", "?") for n in nodes.values() if n["kind"] == "device")),
        "directives": dict(Counter(d["name"] for d in c.get("directives", []))),
        "diagnostics": dict(Counter(d["code"] for d in c.get("diagnostics", []))),
        "unresolved": len(g.get("unresolved", [])),
        "files": len(c.get("files", [])), "definitions": len(c.get("definitions", {})), "models": len(c.get("models", {})),
        "params": len(c.get("params", {})), "nets": len(c.get("nets", {})),
        "index": {k: v for k, v in g["meta"].get("index", {}).items() if k != "deps"},
    }


def timed_extract(entry: str, root: str, **kw):
    from hx.api import extract
    t0 = time.time()
    g = extract(entry, root=root, **kw)
    return g, round(time.time() - t0, 3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--ngspice", default=None, help="ngspice executable (default: registry lookup)")
    ap.add_argument("--timeout", type=float, default=180.0)
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(os.path.join(out, "graphs"), exist_ok=True)
    import hx
    from hx.netlist.check import check_ngspice
    from hx.tools import find_tool
    commands: list[str] = []
    report: dict = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "hx": getattr(hx, "__version__", "?"),
                    "hx_src": HX, "apragma": APRAGMA, "out": out, "thresholds": THRESHOLDS, "examples": [], "sky130": {}, "checks": []}
    ok_all = True

    def check(name: str, ok: bool, detail=""):
        nonlocal ok_all
        report["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
        ok_all &= bool(ok)
        print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail else ""))

    # ---------------------------------------------------------------- apragma examples (mirrored)
    mirror = os.path.join(out, "apragma-mirror")
    shutil.rmtree(mirror, ignore_errors=True)
    os.makedirs(mirror)
    os.symlink(os.path.join(APRAGMA, "models"), os.path.join(mirror, "models"))
    for rel in EXAMPLES:
        src_dir = os.path.join(APRAGMA, os.path.dirname(rel))
        dst_dir = os.path.join(mirror, os.path.dirname(rel))
        os.makedirs(dst_dir, exist_ok=True)
        for f in os.listdir(src_dir):                                  # the deck and its sibling includes, files only
            p = os.path.join(src_dir, f)
            if os.path.isfile(p):
                shutil.copy(p, os.path.join(dst_dir, f))
    commands.append(f"# apragma examples copied to {mirror} (models -> {APRAGMA}/models)")
    ngspice = a.ngspice or find_tool("ngspice")
    for rel in EXAMPLES:
        entry = rel + ":."
        rec: dict = {"deck": rel, "entry": entry}
        commands.append(f"hx extract {entry} --all --dialect auto --root {mirror}")
        try:
            g, secs = timed_extract(entry, mirror, depth=None, dialect="auto")
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"
            report["examples"].append(rec)
            check(f"{rel}: extracts", False, rec["error"])
            continue
        gd = g.to_dict()
        name = os.path.basename(rel).replace(".", "_")
        g.save(os.path.join(out, "graphs", f"{name}.json"))
        rec.update({"seconds": secs, "graph": f"graphs/{name}.json", "stats": stats(gd), "dialect": gd["meta"]["extract_args"]["dialect"]})
        s = rec["stats"]
        check(f"{rel}: 0 unparsed statements", s["diagnostics"].get("unparsed-statement", 0) == 0, json.dumps(s["diagnostics"]))
        check(f"{rel}: 0 unknown device families", s["diagnostics"].get("unknown-device-family", 0) == 0, json.dumps(s["families"]))
        check(f"{rel}: has device nodes", s["nodes"].get("device", 0) > 0, json.dumps(s["nodes"]))
        # oracle
        if ngspice is None:
            rec["oracle"] = {"status": "unavailable", "reason": "ngspice not installed"}
            check(f"{rel}: ngspice present", False, "ngspice not installed")
        else:
            deck_dir = os.path.join(mirror, os.path.dirname(rel))
            if rel == NUMERIC:                                           # the simulator must accept the raw deck first
                cmd = [ngspice, "-n", "-b", os.path.basename(rel)]
                commands.append("cd " + deck_dir + " && " + " ".join(cmd))
                env = {k: v for k, v in os.environ.items() if k != "DISPLAY"}
                try:
                    r = subprocess.run(cmd, cwd=deck_dir, capture_output=True, text=True, timeout=a.timeout, env=env)
                    rec["ngspice_raw"] = {"exit": r.returncode, "stderr_tail": r.stderr[-400:]}
                    check(f"{rel}: raw deck simulates (ngspice exit 0)", r.returncode == 0, f"exit {r.returncode}")
                except subprocess.TimeoutExpired:
                    rec["ngspice_raw"] = {"exit": None, "stderr_tail": "timeout"}
                    check(f"{rel}: raw deck simulates (ngspice exit 0)", False, "timeout")
            commands.append(f"hx netlist check {entry} --oracle ngspice --root {mirror} --json")
            t0 = time.time()
            try:
                rep = check_ngspice(entry, root=mirror, exe=ngspice, dialect="auto", timeout=a.timeout)
            except Exception as e:  # noqa: BLE001
                rep = {"status": "unavailable", "reason": f"{type(e).__name__}: {e}"}
            rep["seconds"] = round(time.time() - t0, 3)
            rec["oracle"] = {k: v for k, v in rep.items() if k != "render"}
            with open(os.path.join(out, "graphs", f"{name}.oracle.json"), "w") as fh:
                json.dump(rep, fh, indent=1)
            if rel == NUMERIC:
                check(f"{rel}: oracle agrees, 0 mismatches", rep.get("status") == "agree" and not rep.get("mismatches"),
                      json.dumps(rep.get("summary")) + (" " + str(rep.get("reason")) if rep.get("reason") else ""))
            elif rel == SYMBOLIC:
                check(f"{rel}: oracle unavailable (symbolic template)", rep.get("status") == "unavailable", str(rep.get("reason", ""))[:160])
            else:
                rec["oracle"]["note"] = "informational"
        report["examples"].append(rec)

    # ---------------------------------------------------------------- sky130 wrapper
    sky = os.path.join(out, "sky130")
    shutil.rmtree(sky, ignore_errors=True)
    os.makedirs(sky)
    wrapper = os.path.join(sky, "sky130_tt.sp")
    with open(wrapper, "w") as fh:
        fh.write(f"* sky130 tt corner wrapper (hx coverage)\n.lib \"{os.path.abspath(SKY130_LIB)}\" tt\n.end\n")
    srec: dict = {"wrapper": wrapper, "lib": os.path.abspath(SKY130_LIB), "exists": os.path.exists(SKY130_LIB)}
    report["sky130"] = srec
    if not os.path.exists(SKY130_LIB):
        check("sky130: library present", False, SKY130_LIB)
    else:
        commands.append(f"hx extract sky130_tt.sp:. --all --dialect ngspice --root {sky}   # cold, then warm")
        shutil.rmtree(os.path.join(sky, ".hx"), ignore_errors=True)
        g_cold, cold = timed_extract("sky130_tt.sp:.", sky, depth=None, dialect="ngspice")
        g_warm, warm = timed_extract("sky130_tt.sp:.", sky, depth=None, dialect="ngspice")
        from hx.api import make_frontend
        fe, _info = make_frontend("spice", sky, deck="sky130_tt.sp", dialect="ngspice")
        fe.build_index()
        decls = {k: sum(1 for _ in fe.index.all_decls(k)) for k in ("subckt", "model", "param")}
        gw = g_warm.to_dict()
        srec.update({"cold_seconds": cold, "warm_seconds": warm, "declarations": decls, "stats": stats(gw),
                     "index_cached": gw["meta"]["index"].get("cached"), "index_parsed": gw["meta"]["index"].get("parsed")})
        g_warm.save(os.path.join(out, "graphs", "sky130_tt.json"))
        check("sky130: cold extract within threshold", cold <= THRESHOLDS["sky130_cold_seconds"], f"{cold}s (<= {THRESHOLDS['sky130_cold_seconds']}s)")
        check("sky130: warm extract within threshold", warm <= THRESHOLDS["sky130_warm_seconds"], f"{warm}s (<= {THRESHOLDS['sky130_warm_seconds']}s)")
        check("sky130: nonzero declaration count", sum(decls.values()) > 0, json.dumps(decls))
        check("sky130: warm run served from the cache", (gw["meta"]["index"].get("parsed") == 0) and gw["meta"]["index"].get("cached", 0) > 0,
              json.dumps({k: gw["meta"]["index"].get(k) for k in ("parsed", "cached", "files")}))
        # A definition view is addressed through its DEFINING file (the entry rule), which the index knows.
        decl = next(iter(fe.index.decls.get(("subckt", (), SKY130_DEF.lower()), [])), None)
        declaring = decl.file if decl else None
        entry = f"{declaring}:@{SKY130_DEF}" if declaring else f"sky130_tt.sp:@{SKY130_DEF}"
        commands.append(f"hx extract {entry} --all --deck sky130_tt.sp --dialect ngspice --root {sky}")
        try:
            if declaring is None:
                raise LookupError(f"no .subckt {SKY130_DEF} in the tt closure")
            g_def, dsecs = timed_extract(entry, sky, depth=None, dialect="ngspice", deck="sky130_tt.sp")
            gd = g_def.to_dict()
            g_def.save(os.path.join(out, "graphs", f"sky130_{SKY130_DEF}.json"))
            defs = gd.get("circuit", {}).get("definitions", {})
            key = next((k for k in defs if k.split("/")[-1] == SKY130_DEF), None)
            srec["definition_view"] = {"entry": entry, "seconds": dsecs, "root_id": gd["entry"], "nodes": dict(Counter(n["kind"] for n in gd["nodes"].values())),
                                       "declaring_file": declaring, "declaring_line": decl.line, "status": defs[key]["status"] if key else None}
            check(f"sky130: definition view of {SKY130_DEF}", key is not None and gd["entry"].endswith(f"@{SKY130_DEF}") and defs[key]["status"] == "found",
                  json.dumps(srec["definition_view"]))
        except Exception as e:  # noqa: BLE001
            srec["definition_view"] = {"entry": entry, "error": f"{type(e).__name__}: {e}"}
            check(f"sky130: definition view of {SKY130_DEF}", False, srec["definition_view"]["error"])

    # ---------------------------------------------------------------- outputs
    report["ok"] = ok_all
    with open(os.path.join(out, "coverage.json"), "w") as fh:
        json.dump(report, fh, indent=1)
    with open(os.path.join(out, "commands.txt"), "w") as fh:
        fh.write("\n".join(commands) + "\n")
    md = [f"# Netlist coverage {report['generated']}", "", f"hx {report['hx']} at `{HX}`; apragma `{APRAGMA}`; out `{out}`", "",
          "## Checks", "", "| check | ok | detail |", "|---|---|---|"]
    md += [f"| {c['check']} | {'yes' if c['ok'] else 'NO'} | {str(c['detail']).replace('|', '/')} |" for c in report["checks"]]
    md += ["", "## Examples", "", "| deck | dialect | s | nodes | families | directives | diagnostics | unresolved | oracle |", "|---|---|---|---|---|---|---|---|---|"]
    for r in report["examples"]:
        s = r.get("stats", {})
        o = r.get("oracle", {})
        osum = o.get("status", "-") + (" " + json.dumps(o.get("summary")) if o.get("summary") else "") + ((" " + str(o.get("reason"))[:80]) if o.get("reason") else "")
        md.append(f"| {r['deck']} | {r.get('dialect', '-')} | {r.get('seconds', '-')} | {json.dumps(s.get('nodes'))} | {json.dumps(s.get('families'))} | "
                  f"{json.dumps(s.get('directives'))} | {json.dumps(s.get('diagnostics'))} | {s.get('unresolved', '-')} | {osum.replace('|', '/')} |"
                  if "stats" in r else f"| {r['deck']} | error | {r.get('error')} |")
    sk = report["sky130"]
    md += ["", "## sky130 wrapper", "", f"- library `{sk.get('lib')}` (exists: {sk.get('exists')})",
           f"- cold {sk.get('cold_seconds')} s, warm {sk.get('warm_seconds')} s (index parsed {sk.get('index_parsed')}, cached {sk.get('index_cached')})",
           f"- declarations {json.dumps(sk.get('declarations'))}", f"- definition view {json.dumps(sk.get('definition_view'))}", "",
           f"Result: {'all checks passed' if ok_all else 'FAILED checks present'}", ""]
    with open(os.path.join(out, "coverage.md"), "w") as fh:
        fh.write("\n".join(md))
    print(f"wrote {out}/coverage.json, coverage.md, commands.txt, graphs/  ->  {'OK' if ok_all else 'FAIL'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
