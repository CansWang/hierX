"""Runs the Node unit tests for the viewer's merge-patch helpers (hx/viewer/patch.js)."""
import os
import shutil
import subprocess

import pytest

from conftest import require_tool

HERE = os.path.dirname(__file__)


def test_patch_js_unit_tests():
    node = require_tool("node")
    r = subprocess.run([node, "--test", os.path.join(HERE, "js")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "# fail 0" in r.stdout


def test_patch_js_is_served_and_inlined(extract, cproj):
    from hx.export import build_html
    html = build_html(extract(depth=1).to_dict(), {})
    assert "root.hxPatch = factory()" in html and '<script src="/static/patch.js">' not in html
