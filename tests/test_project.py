"""Tracked entries, update/snapshot/history, watch, diff CLI and hook install on the C fixture."""
import json
import os
import subprocess
import sys
import threading
import time

from hx import project


def run(args, cwd, stdin=None):
    return subprocess.run([sys.executable, "-m", "hx.cli", *args], cwd=cwd, capture_output=True, text=True, input=stdin)


def _bump(path):
    os.utime(path, (time.time() + 5, time.time() + 5))


def test_track_config_roundtrip(cproj):
    t = project.track(str(cproj), "src/main.c:app_run", depth=2, exclude=["third_party/*"], include_callers=True, lsp_timeout=None)
    assert t == {"entry": "src/main.c:app_run", "depth": 2, "exclude": ["third_party/*"], "include_callers": True}
    project.track(str(cproj), "src/hal.c:hal_write32", depth=1)
    cfg = project.load_config(str(cproj))
    assert [e["entry"] for e in cfg["entries"]] == ["src/main.c:app_run", "src/hal.c:hal_write32"]
    assert cfg["watch"]["history"] == 20
    txt = open(project.config_path(str(cproj))).read()
    assert '[[entries]]\nentry = "src/main.c:app_run"\ndepth = 2' in txt and 'exclude = ["third_party/*"]' in txt
    project.track(str(cproj), "src/main.c:app_run", depth=4)       # replace keeps one entry per id
    assert [e["depth"] for e in project.load_config(str(cproj))["entries"] if e["entry"] == "src/main.c:app_run"] == [4]
    assert project.untrack(str(cproj), "src/hal.c:hal_write32") and not project.untrack(str(cproj), "nope")
    assert project.slug("src/main.c:app_run").startswith("src__main.c__app_run-") and len(project.slug("src/main.c:app_run")) == len("src__main.c__app_run-") + 6
    assert project.slug("a/b.c:f") != project.slug("a__b.c:f")       # review finding H5: the old slug mapped both to one file


def test_update_snapshots_and_diffs(cproj):
    root = str(cproj)
    project.track(root, "src/main.c:app_run", depth=3, jobs=1)
    r1 = project.update(root)
    assert len(r1) == 1 and r1[0].previous is None and r1[0].error is None and os.path.exists(r1[0].graph_path)
    assert "first extraction" in r1[0].markdown and not r1[0].changed
    last = open(os.path.join(project.hx_dir(root), "last-diff.md")).read()
    assert "first extraction" in last
    r2 = project.update(root)                      # nothing changed: snapshot taken, diff empty
    assert r2[0].previous and os.path.exists(r2[0].previous) and not r2[0].changed
    assert "No structural changes" in open(os.path.join(project.hx_dir(root), "last-diff.md")).read()
    dma_c = cproj / "src" / "dma.c"
    dma_c.write_text(dma_c.read_text().replace("    g_dma_active++;\n", "    g_dma_active += 2;\n    hal_read32(ch->base);\n"))
    _bump(dma_c)
    r3 = project.update(root)
    assert r3[0].changed and "dma_start" in r3[0].markdown and "calls +hal_read32" in r3[0].markdown
    hist = project.list_history(root, "src/main.c:app_run")
    assert len(hist) == 2 and project.resolve_history(root, "src/main.c:app_run", "prev")["ts"] == hist[-1]["ts"]
    assert project.resolve_history(root, "src/main.c:app_run", hist[0]["ts"])["ts"] == hist[0]["ts"]
    assert project.resolve_history(root, "src/main.c:app_run", "1999-01-01T00:00:00+00:00")["ts"] == hist[0]["ts"]
    graphs = project.find_graphs(root)
    assert graphs[0]["name"] == project.slug("src/main.c:app_run") and graphs[0]["entry"] == "c:src/main.c::app_run"
    project.prune_history(root, "src/main.c:app_run", 1)
    assert len(project.list_history(root, "src/main.c:app_run")) == 1
    summary = project.summarize(r3)
    assert summary.startswith("~ src/main.c:app_run: functions +0 −0 ~1")


def test_update_tolerates_bad_entry(cproj):
    root = str(cproj)
    project.track(root, "src/main.c:nope", jobs=1)
    project.track(root, "src/hal.c:hal_read32", depth=1, jobs=1)
    res = project.update(root)
    assert res[0].error and "not found" in res[0].error and res[1].error is None
    assert "extraction failed" in open(os.path.join(project.hx_dir(root), "last-diff.md")).read()


def test_cli_update_diff_and_hook_mode(cproj):
    r = run(["track", "src/main.c:app_run", "--depth", "2"], cwd=cproj)
    assert r.returncode == 0 and "tracking" in r.stdout
    r = run(["track", "--list"], cwd=cproj)
    assert "src/main.c:app_run" in r.stdout and "depth=2" in r.stdout
    r = run(["update"], cwd=cproj)
    assert r.returncode == 0 and "first extraction" in r.stdout and "last-diff.md" in r.stdout
    main_c = cproj / "src" / "main.c"
    main_c.write_text(main_c.read_text().replace("    hal_board_init();", "    hal_board_init();\n    hal_read32((void *)0);"))
    _bump(main_c)
    r = run(["update", "--quiet", "--hook"], cwd=cproj, stdin='{"hook_event_name":"Stop"}')
    assert r.returncode == 0 and r.stdout.startswith("~ src/main.c:app_run:")
    r = run(["diff", "--entry", "src/main.c:app_run", "--exit-code"], cwd=cproj)
    assert r.returncode == 1 and "calls +hal_read32" in r.stdout and "since" in r.stdout
    r = run(["diff", "--entry", "src/main.c:app_run", "--format", "json"], cwd=cproj)
    assert json.loads(r.stdout)["schema"] == "hx-diff/1"
    hist = project.list_history(str(cproj), "src/main.c:app_run")
    gp = project.graph_path(str(cproj), "src/main.c:app_run")
    r = run(["diff", hist[0]["path"], gp, "-o", "out/d.md"], cwd=cproj)
    assert r.returncode == 0 and "calls +hal_read32" in (cproj / "out" / "d.md").read_text()
    r = run(["update", "--json"], cwd=cproj)
    assert json.loads(r.stdout)[0]["diff"]["summary"]["any"] is False


def test_hook_print_and_install(cproj):
    r = run(["hook", "print"], cwd=cproj)
    snippet = json.loads(r.stdout)
    assert snippet["hooks"]["Stop"][0]["hooks"][0]["command"] == "hx update --quiet --hook"
    r = run(["hook", "install"], cwd=cproj)
    assert r.returncode == 0 and r.stdout.startswith("installed")
    settings = json.load(open(cproj / ".claude" / "settings.json"))
    assert settings["hooks"]["Stop"][0]["hooks"][0]["command"] == "hx update --quiet --hook"
    r = run(["hook", "install"], cwd=cproj)
    assert r.stdout.startswith("already set")
    (cproj / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"PostToolUse": []}}))
    path, added = project.install_hook(str(cproj), "PostToolUse")
    s2 = json.load(open(path))
    assert added and s2["permissions"] == {"allow": ["Bash(ls)"]} and s2["hooks"]["PostToolUse"][0]["matcher"] == "Edit|Write|MultiEdit|NotebookEdit"


def test_watch_runs_update_after_quiet_period(cproj):
    root = str(cproj)
    project.track(root, "src/hal.c:hal_write32", depth=1, jobs=1)
    seen = []
    done = threading.Event()

    def on_update(res):
        seen.append(res)
        if len(seen) >= 2:
            done.set()
    t = threading.Thread(target=project.watch, kwargs=dict(root=root, interval=0.2, debounce=0.3, max_updates=2, on_update=on_update), daemon=True)
    t.start()
    deadline = time.time() + 10
    while len(seen) < 1 and time.time() < deadline:
        time.sleep(0.05)
    assert len(seen) == 1 and seen[0][0].previous is None
    hal_c = cproj / "src" / "hal.c"
    hal_c.write_text(hal_c.read_text().replace("    *addr = val;\n", "    *addr = val;\n    *addr = val;\n"))
    _bump(hal_c)
    assert done.wait(15), "watch did not react to the change"
    t.join(5)
    assert seen[1][0].changed and "body changed" in seen[1][0].markdown
    r = run(["watch", "--once"], cwd=cproj)
    assert r.returncode == 0 and "= src/hal.c:hal_write32: no structural change" in r.stdout
