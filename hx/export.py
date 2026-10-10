"""Build a standalone viewer HTML with the graph, annotations, CSS and JS inlined."""
from __future__ import annotations

import json
import os
import re

VIEWER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer")


def _read(name: str) -> str:
    with open(os.path.join(VIEWER_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def _inline_json(obj) -> str:
    # "</script>" inside the payload would terminate the data block
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def build_html(graph: dict, annotations: dict | None = None) -> str:
    html = _read("index.html")
    html = re.sub(r'<link rel="stylesheet" href="/static/style.css">', lambda m: "<style>\n" + _read("style.css") + "\n</style>", html)
    for name in ("vendor/cytoscape.min.js", "vendor/dagre.min.js", "vendor/cytoscape-dagre.js", "patch.js", "app.js"):
        tag = f'<script src="/static/{name}"></script>'
        assert tag in html, f"index.html lacks {tag}"
        html = html.replace(tag, "<script>\n" + _read(name).replace("</script>", "<\\/script>") + "\n</script>")
    cfg = {"mode": "export", "allow_extract": False}
    html = html.replace('window.HX_CONFIG = {mode: "serve"};', f"window.HX_CONFIG = {json.dumps(cfg)};")
    data_block = ('<script type="application/json" id="hx-graph">' + _inline_json(graph) + "</script>\n"
                  '<script type="application/json" id="hx-annotations">' + _inline_json(annotations or {}) + "</script>")
    html = html.replace("<!--HX:DATA-->", data_block)
    return html


def export_file(graph_path: str, out_path: str, annotations_path: str | None = None) -> str:
    from . import annotations as ann_mod
    from .graphio import load_graph_dict
    graph = load_graph_dict(graph_path)
    ann_path = annotations_path or os.path.join(os.path.dirname(os.path.abspath(graph_path)), "annotations.json")
    ann = ann_mod.load(ann_path) if os.path.exists(ann_path) else ann_mod.empty()
    html = build_html(graph, ann)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path
