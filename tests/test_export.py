import json
import subprocess
import sys

from hx.export import build_html, export_file


def test_build_html_inlines_everything(extract):
    g = extract(depth=2).to_dict()
    html = build_html(g, {"nodes": {"c:src/dma.c::dma_start": {"note": "x</script><b>"}}})
    assert "/static/" not in html                      # nothing left to fetch
    assert 'window.HX_CONFIG = {"mode": "export", "allow_extract": false};' in html
    assert '<script type="application/json" id="hx-graph">' in html
    assert "<\\/script><b>" in html and "x</script><b>" not in html   # payload cannot break out of its block
    assert "cytoscape" in html and "dagre" in html
    data = html.split('id="hx-graph">', 1)[1].split("</script>", 1)[0]
    assert json.loads(data)["entry"] == "c:src/main.c::app_run"


def test_export_cli(cproj, extract):
    gp = cproj / ".hx" / "graph.json"
    extract(depth=2).save(str(gp))
    (cproj / ".hx" / "annotations.json").write_text(json.dumps({"schema": "hx-ann/1", "nodes": {"a": {"note": "n"}}}))
    r = subprocess.run([sys.executable, "-m", "hx.cli", "export", str(gp), "-o", str(cproj / "out" / "view.html")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    html = (cproj / "out" / "view.html").read_text()
    assert '"note": "n"' in html or '"note":"n"' in html
    out = export_file(str(gp), str(cproj / "out" / "v2.html"))
    assert out.endswith("v2.html")
