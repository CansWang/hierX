"""Independent Xyce/XDM checks. Inputs are mirrored source files, never emitted device records."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import os
import re
import subprocess
import tempfile

from ..api import extract
from ..tools import resolve_tool
from .names import split_path
from .profiles import XYCE_INVENTORY


def mirror_sources(graph, root, directory, search_paths=()):
    """Copy the observed closure and rewrite only include filenames into an isolated directory."""
    paths = {Path(f["path"]) if Path(f["path"]).is_absolute() else Path(root) / f["path"]
             for f in graph["circuit"]["files"]}
    paths = {p.resolve() for p in paths}
    mapping = {p: Path(directory) / (hashlib.sha256(str(p).encode()).hexdigest()[:12] + "-" + p.name) for p in paths}
    include = re.compile(r'^(\s*\.(?:include|inc|lib)\s+)("[^"]*"|\x27[^\x27]*\x27|\S+)(.*)$', re.I)
    for source, dest in mapping.items():
        lines = []
        for line in source.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True):
            m = include.match(line.rstrip("\r\n"))
            if m:
                name = m[2].strip('"\x27')
                candidates = ([Path(name)] if Path(name).is_absolute() else
                              [source.parent / name, *(Path(root) / p / name for p in search_paths), Path(root) / name])
                target = next((p.resolve() for p in candidates if p.resolve() in mapping), None)
                if target:
                    line = m[1] + '"' + str(mapping[target]) + '"' + m[3] + "\n"
            lines.append(line)
        dest.write_text("".join(lines), encoding="utf-8")
    deck = Path(graph["circuit"]["deck"])
    deck = (deck if deck.is_absolute() else Path(root) / deck).resolve()
    return mapping[deck], mapping


def family_counts(graph):
    result = Counter()
    for n in graph["nodes"].values():
        if n["kind"] != "device":
            continue
        family = n["attrs"]["family"]
        if family.startswith("Y"):
            family = family[1:]
        result[family.upper()] += 1
    # Xyce replaces a connected group of mutually coupled inductors by one K
    # device; the source graph deliberately retains each L and K statement.
    groups = []
    for n in graph["nodes"].values():
        if n.get("attrs", {}).get("family") == "K":
            targets = {t for c in n["attrs"].get("controls", []) for t in c.get("targets", [])}
            overlap = [g for g in groups if g & targets]
            for g in overlap:
                targets |= g
                groups.remove(g)
            groups.append(targets)
    if groups:
        result["L"] -= len(set().union(*groups))
        if not result["L"]:
            del result["L"]
        result["K"] = len(groups)
    return result


def check_external(entry, *, root, oracle="xyce", exe=None, dialect="auto", deck=None, search_paths=(), timeout=120):
    exe = resolve_tool(oracle, exe)
    dialect = "xyce" if dialect == "auto" else dialect
    g = extract(entry, root=root, depth=None, dialect=dialect, deck=deck, search_paths=search_paths, use_cache=False).to_dict()
    c = g["circuit"]
    report = {"entry": entry, "oracle": oracle, "exe": exe, "status": "unavailable", "summary": {},
              "mismatches": [], "checked": [], "scope": "whole deck", "reason": None}
    if c["root"].get("deck_role") != "deck":
        report["reason"] = "no deck context; pass --deck for a standalone definition"
        return report
    if c["root"]["kind"] != "deck" or g["nodes"][g["entry"]]["kind"] != "module":
        g = extract(c["deck"] + ":.", root=root, depth=None, dialect=dialect, search_paths=search_paths, use_cache=False).to_dict()
    with tempfile.TemporaryDirectory(prefix="hx-" + oracle + "-") as work:
        mirrored, mapping = mirror_sources(g, root, work, search_paths)
        def run(args):
            return subprocess.run([exe, *args], cwd=work, capture_output=True, text=True, timeout=timeout)
        try:
            if oracle == "xyce":
                proc = run(["-syntax", str(mirrored)])
                report["checked"].append("original-deck syntax")
                report["stdout"], report["stderr"] = proc.stdout[-12000:], proc.stderr[-4000:]
                if proc.returncode:
                    report["reason"] = f"Xyce rejected the deck (exit {proc.returncode}); see stdout/stderr"
                    return report
                sim = Counter({m[1].upper(): int(m[2]) for m in
                               re.finditer(r"^\s+([A-Za-z][A-Za-z0-9_-]*)\s+(\d+)\s*$", proc.stdout, re.M)})
                hx = family_counts(g)
                if sim:
                    report["checked"].append("device-family counts")
                    for k in sorted(set(sim) | set(hx)):
                        if sim[k] != hx[k]:
                            report["mismatches"].append({"what": "family count", "path": k, "hx": hx[k], "oracle": sim[k]})
                names_path = Path(work) / "names.txt"
                topo = run(["-norun", "-namesfile", str(names_path), str(mirrored)])
                report["topology_stdout"] = topo.stdout[-12000:]
                if topo.returncode or not names_path.exists():
                    report["reason"] = "Xyce topology/names unavailable: " + (topo.stdout + topo.stderr)[-1500:]
                    return report
                names = [line.split()[-1].lower() for line in names_path.read_text().splitlines() if len(line.split()) >= 2]
                expected = {r.get("canonical", r["net"]) for rows in g["circuit"].get("terminals", {}).values() for r in rows}
                expected.discard("0")
                for net in sorted(expected):
                    spelling = ":".join(split_path(net)).lower()
                    if spelling not in names:
                        report["mismatches"].append({"what": "exposed net", "path": net, "hx": spelling, "oracle": None})
                report["checked"].extend(["topology acceptance", "exposed net names"])
                report["summary"] = {"hx_families": dict(hx), "oracle_families": dict(sim), "exposed_names": names}
            else:
                proc = run(["-s", "xyce", "--auto", "-q", "ALL", "-d", str(Path(work) / "xdm-output"), str(mirrored)])
                report["stdout"], report["stderr"] = proc.stdout[-12000:], proc.stderr[-4000:]
                warnings = [s for s in (proc.stdout + "\n" + proc.stderr).splitlines()
                            if re.search(r"\b(WARNING|ERROR|CRITICAL):", s, re.I)]
                if proc.returncode or warnings:
                    report["reason"] = "XDM coverage unavailable: " + "\n".join(warnings or [proc.stderr[-1500:], proc.stdout[-1500:]])
                    return report
                actual = set()
                for line in proc.stdout.splitlines():
                    m = re.match(r"^(.+?)\s*,\s*(\d+)\s*,\s*([^,]+)\s*,", line)
                    if m:
                        actual.add((m[1].strip(), int(m[2]), m[3].strip().lower()))
                expected = set()
                unsupported_u = set()
                for n in g["nodes"].values():
                    # XDM 2.7's query index is local to the top-level scope and
                    # excludes subcircuit instances. Do not claim to verify them.
                    if n["kind"] != "device" or n.get("depth") != 1:
                        continue
                    loc = n["loc"]
                    source = (Path(root) / loc["file"]).resolve()
                    name = n["name"].lower()
                    if "!" in name:
                        name = "y" + name.split("!", 1)[1]
                    expected.add((mapping[source].name, loc["line"], name))
                    if n.get("attrs", {}).get("family") == "U":
                        unsupported_u.add((mapping[source].name, loc["line"], name))
                missing_u = (expected - actual) & unsupported_u
                if missing_u:
                    report["reason"] = "XDM query omits U digital devices: " + repr(sorted(missing_u))
                    report["unverified"] = ["U digital devices", "subcircuit inventory", "terminal bindings", "model values"]
                    return report
                for row in sorted(expected ^ actual):
                    report["mismatches"].append({"what": "source device inventory", "path": str(row), "hx": row in expected, "oracle": row in actual})
                report["checked"].extend(["XDM parse acceptance", "top-level primitive inventory"])
                report["unverified"] = ["subcircuit inventory", "terminal bindings", "model values"]
                report["summary"] = {"hx_devices": len(expected), "oracle_devices": len(actual)}
                if not expected:
                    report["reason"] = "XDM query exposes no top-level primitives to compare"
                    return report
        except subprocess.TimeoutExpired:
            report["reason"] = f"{oracle} timed out after {timeout:g}s"
            return report
        except OSError as exc:
            report["reason"] = f"cannot execute {oracle}: {exc}"
            return report
    report["status"] = "mismatch" if report["mismatches"] else "agree"
    return report
