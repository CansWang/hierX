#!/usr/bin/env python3
"""Explicit pinned production acceptance; no network or corpus downloads in normal pytest.

Run with .venv/bin/python dev/scripts/hardening_coverage.py --codex-root CHECKOUT --out ARTIFACTS.
The checkout must be the pinned Codex revision; tools/dependencies must already be installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
PIN = "221e4e7c05386d06aa7b91da2a9b04f7f2bd921f"
ENTRIES = [
    "utils/absolute-path/src/lib.rs:AbsolutePathBuf::resolve_path_against_base",
    "utils/absolute-path/src/lib.rs:<AbsolutePathBuf as TryFrom<&str>>::try_from",
    "utils/absolute-path/src/lib.rs:<AbsolutePathBuf as TryFrom<String>>::try_from",
    "async-utils/src/lib.rs:<F as OrCancelExt>::or_cancel",
    "file-search/src/lib.rs:run_main", "file-search/src/lib.rs:create_session",
    "exec/src/lib.rs:run_main", "cli/src/main.rs:cli_main",
]


def source_fingerprint():
    """Include uncommitted runtime changes in the reproducibility record."""
    files = {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((REPO / "hx").rglob("*"))
             if p.is_file() and p.suffix in (".py", ".js", ".json", ".html", ".css")}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def worker(args):
    from hx.api import make_frontend, split_entry
    from hx.traverse import TraverseOptions, extract_graph
    root, out = Path(args.codex_root).resolve() / "codex-rs", Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fingerprint = source_fingerprint()
    fe, _ = make_frontend("rust", str(root), lsp_cmd=[args.rustup, "run", "1.95.0", "rust-analyzer"], lsp_timeout=300)
    def timeout_case(_signum, _frame):
        raise TimeoutError("production extraction exceeded 900 seconds")
    signal.signal(signal.SIGALRM, timeout_case)
    results = []
    original_request = fe._req
    def observe_request(method, params, timeout=None):
        (out / "progress.json").write_text(json.dumps({"method": method, "requests": fe.requests, "time": time.time()}))
        return original_request(method, params, timeout)
    fe._req = observe_request
    try:
        indices = list(range(len(ENTRIES)))
        if args.worker == "reverse":
            indices.reverse()
        for i in indices:
            entry = ENTRIES[i]
            for label, depth, callers in (("d0", 0, False), ("d2", 2, False), ("callers", 1, True)):
                t0, before = time.monotonic(), fe.requests
                try:
                    signal.alarm(900)
                    file, symbol = split_entry(entry)
                    g = extract_graph(fe, file, symbol, TraverseOptions(depth=depth, include_callers=callers, max_nodes=200), str(root))
                    g.meta.update(entry_arg=entry, extract_args={"entry": entry, "root": str(root), "depth": depth,
                                  "max_nodes": 200, "include_callers": callers}, index=dict(fe.stats))
                    path = out / f"{i}-{label}.json"
                    g.save(str(path))
                    result = {"entry": entry, "case": label, "graph": str(path), "nodes": len(g.nodes), "edges": len(g.edges),
                              "seconds": round(time.monotonic() - t0, 3), "requests": fe.requests - before, "ok": True}
                except Exception as exc:
                    result = {"entry": entry, "case": label, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
                finally:
                    signal.alarm(0)
                results.append(result)
                (out / "cases.json").write_text(json.dumps(results, indent=2) + "\n")
                print(json.dumps(result), flush=True)
    finally:
        (out / "session.json").write_text(json.dumps({"hx_source_sha256": fingerprint, "index": fe.stats}, indent=2) + "\n")
        fe.close()
        (out / "cases.json").write_text(json.dumps(results, indent=2) + "\n")
    return 0 if all(r["ok"] for r in results) else 1


def rust_suite(args, stage):
    root, out = Path(args.codex_root).resolve(), Path(args.out).resolve()
    revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if revision != PIN:
        raise RuntimeError(f"Codex revision {revision} differs from pinned {PIN}")
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("Codex checkout has local changes; use a clean dedicated checkout")
    stage("codex-revision", lambda: {"commit": revision, "lock_sha256": hashlib.sha256((root / "codex-rs/Cargo.lock").read_bytes()).hexdigest()})
    env = dict(os.environ, CARGO_TARGET_DIR=str(out / "codex-target"))
    env["PATH"] = str(Path(args.rustup).parent) + os.pathsep + env.get("PATH", "")
    def run(cmd, *, timeout=900, cwd=REPO):
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        if p.returncode:
            raise RuntimeError(f"exit {p.returncode}: " + (p.stdout + p.stderr)[-5000:])
        return p.stdout
    stage("rust-toolchain", lambda: {"rustc": run([args.rustup, "run", "1.95.0", "rustc", "--version"]).strip(),
                                      "rust_analyzer": run([args.rustup, "run", "1.95.0", "rust-analyzer", "--version"]).strip()})
    for order in ("forward", "reverse"):
        cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", order, "--codex-root", str(root),
               "--out", str(out / order), "--rustup", args.rustup]
        def batch(cmd=cmd, order=order):
            text = run(cmd, timeout=24 * 900 + 330)
            (out / f"{order}.log").write_text(text)
            return json.loads((out / order / "cases.json").read_text())
        stage("rust-" + order, batch)
    def stable():
        from hx.diff import diff_graphs
        differences = []
        for order in ("forward", "reverse"):
            session = json.loads((out / order / "session.json").read_text())
            if session["hx_source_sha256"] != source_fingerprint():
                raise RuntimeError("hx runtime changed during acceptance; rerun both sessions")
        for p in sorted((out / "forward").glob("*-*.json")):
            a, b = json.loads(p.read_text()), json.loads((out / "reverse" / p.name).read_text())
            d = diff_graphs(a, b)
            if d["summary"]["any"]:
                differences.append({"case": p.name, "summary": d["summary"]})
            # The user-facing diff groups unresolved reasons, so also check every
            # unresolved identity and call site without discarding multiplicity.
            def unresolved(g):
                return sorted(json.dumps(u, sort_keys=True) for u in g["unresolved"])
            if unresolved(a) != unresolved(b):
                differences.append({"case": p.name, "unresolved_identity_or_site_changed": True})
        if differences:
            raise RuntimeError(json.dumps(differences))
        return {"stable_cases": 24}
    stage("rust-stable-identities", stable)
    oracle_target = out / "oracle-target"
    for operation in ("test", "build"):
        stage("rust-source-oracle-" + operation, lambda operation=operation: run([args.rustup, "run", "1.95.0", "cargo", operation, "--locked",
              "--manifest-path", str(REPO / "dev/rust-oracle/Cargo.toml"), "--target-dir", str(oracle_target)]))
    def audit():
        from hx.ids import squash_ws
        graphs = [json.loads(p.read_text()) for p in sorted((out / "forward").glob("*-*.json"))]
        files = sorted({str(root / "codex-rs" / e["loc"]["file"]) for g in graphs for e in g["edges"]
                        if e.get("loc") and not Path(e["loc"]["file"]).is_absolute()})
        raw = run([str(oracle_target / "debug/hx-rust-source-oracle"), *files])
        (out / "rust-source-inventory.jsonl").write_text(raw)
        inventory, macros = {}, {}
        for line in raw.splitlines():
            rec = json.loads(line)
            file = str(Path(rec["file"]).resolve())
            macros[file] = rec["macros"]
            for call in rec["calls"]:
                # rust-analyzer ranges may name the whole path or its final identifier.
                for pos in (call["start"], call.get("name_start", call["start"])):
                    inventory[(file, pos["line"], pos["column"] + 1)] = call["args"]
        checked, macro_sites, unmapped, mismatches = set(), {}, {}, {}
        for g in graphs:
            for e in g["edges"]:
                loc = e.get("loc")
                if not loc:
                    continue
                file = str((root / "codex-rs" / loc["file"]).resolve())
                site = (file, loc["line"], loc.get("col", 1))
                expected = inventory.get(site)
                if expected is None:
                    position = (site[1], site[2] - 1)
                    macro = next((m for m in macros.get(file, []) if
                                  (m["start"]["line"], m["start"]["column"]) <= position <
                                  (m["end"]["line"], m["end"]["column"])), None)
                    if macro:
                        macro_sites[site] = {"site": site, "name": e.get("name"), "macro": macro,
                                             "reason": "syn treats this macro token body as opaque; semantic target comes from rust-analyzer"}
                    else:
                        unmapped[site] = {"site": site, "name": e.get("name"), "args": e["args"]}
                    continue
                checked.add(site)
                if [squash_ws(s, 'rs') for s in expected] != e["args"]:
                    mismatches[site] = {"site": site, "expected": expected, "actual": e["args"], "name": e.get("name")}
        result = {"checked_source_calls": len(checked), "macro_mapping_gaps": list(macro_sites.values()),
                  "unexpected_mapping_gaps": list(unmapped.values()), "mismatches": list(mismatches.values())}
        (out / "rust-audit.json").write_text(json.dumps(result, indent=2) + "\n")
        if mismatches or unmapped or not checked:
            raise RuntimeError(json.dumps({"checked": len(checked), "mismatches": list(mismatches.values())[:15],
                                           "unexpected_mapping_gaps": list(unmapped.values())[:15]}))
        return {"checked_source_calls": len(checked), "macro_mapping_gaps": len(macro_sites), "unexpected_mapping_gaps": 0}
    stage("rust-source-arguments", audit)


def xyce_suite(args, stage):
    from hx.netlist.xyce import check_external
    from hx.tools import resolve_tool
    root = REPO / "tests/fixtures/xyce"
    cases = json.loads((root / "acceptance.json").read_text())
    def toolchain():
        result = {}
        for name in ("xyce", "xdm"):
            exe = resolve_tool(name, getattr(args, name))
            path = Path(exe).resolve()
            item = {"path": exe, "resolved_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            if name == "xyce":
                proc = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=30, check=True)
                item["version"] = (proc.stdout + proc.stderr).strip()
            else:
                # XDM 2.7 has no --version; retain its bundle label and exact executable hash.
                item["bundle"] = next((p.name for p in path.parents if re.match(r"xdm-\d", p.name, re.I)), None)
            result[name] = item
        return result
    stage("xyce-toolchain", toolchain)
    for name, expected in cases.items():
        for oracle in ("xyce", "xdm"):
            def check(name=name, oracle=oracle, expected=expected):
                report = check_external(name + ":.", root=str(root), oracle=oracle, exe=getattr(args, oracle))
                (Path(args.out) / (name + "." + oracle + ".json")).write_text(json.dumps(report, indent=2) + "\n")
                if report["status"] != expected[oracle]:
                    raise RuntimeError(json.dumps(report))
                if report["status"] == "unavailable" and not re.search(expected["reason"], report.get("reason") or ""):
                    raise RuntimeError("unavailable for an unexpected reason: " + json.dumps(report))
                return {"status": report["status"], "checked": report["checked"], "reason": report.get("reason")}
            stage(name + "-" + oracle, check)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--codex-root")
    p.add_argument("--out", required=True)
    p.add_argument("--suite", choices=["all", "rust", "xyce"], default="all")
    p.add_argument("--rustup", default=shutil.which("rustup") or str(Path.home() / ".cargo/bin/rustup"))
    p.add_argument("--xyce"); p.add_argument("--xdm")
    p.add_argument("--fail-stage", help="force a named stage to fail, testing failure propagation")
    p.add_argument("--worker", choices=["forward", "reverse"], help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.worker:
        return worker(args)
    out = Path(args.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    report = {"command": sys.argv, "hx_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
              "hx_source_sha256": source_fingerprint(), "stages": []}
    failed = False
    def stage(name, action):
        nonlocal failed
        t0 = time.monotonic()
        try:
            if args.fail_stage == name:
                raise RuntimeError("injected stage failure")
            result = action()
            rec = {"name": name, "exit": 0, "result": result}
        except Exception as exc:
            rec = {"name": name, "exit": 1, "error": str(exc)}; failed = True
        rec["seconds"] = round(time.monotonic() - t0, 3)
        report["stages"].append(rec)
        (out / "coverage.json").write_text(json.dumps(report, indent=2) + "\n")
        print(("PASS " if rec["exit"] == 0 else "FAIL ") + name, flush=True)
        if rec["exit"]:
            raise RuntimeError(rec["error"])
    try:
        if args.suite in ("all", "rust"):
            if not args.codex_root:
                raise RuntimeError("--codex-root is required for the Rust corpus")
            rust_suite(args, stage)
        if args.suite in ("all", "xyce"):
            xyce_suite(args, stage)
    except Exception as exc:
        failed = True; report["error"] = str(exc)
    report["exit"] = int(failed)
    (out / "coverage.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "coverage.md").write_text("# Production acceptance\n\n" + "\n".join(f"- {'PASS' if s['exit'] == 0 else 'FAIL'} {s['name']} ({s['seconds']}s)" for s in report["stages"]) + "\n")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
