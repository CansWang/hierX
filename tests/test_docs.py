"""Check user-facing reference coverage without requiring documentation extras."""
import asyncio
import inspect
from pathlib import Path
import re

from mcp.client import Client

from hx.mcp_server import build_server
from hx.serve.app import create_app

DOCS = Path(__file__).resolve().parents[1] / "docs"


def sections(path):
    text = path.read_text(encoding="utf-8")
    return {name: body for name, body in re.findall(r"^## `([^`]+)`\n(.*?)(?=^## |\Z)", text, re.M | re.S)}


def test_http_reference_covers_routes_and_query_arguments(tmp_path):
    documented = sections(DOCS / "reference/http.md")
    app = create_app(str(tmp_path / ".hx/graph.json"), root=str(tmp_path))
    actual = {}
    for route in app.routes:
        if route.path.startswith(("/api/", "/events")):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                actual[f"{method} {route.path}"] = route
    assert documented.keys() == actual.keys()
    for key, route in actual.items():
        for param in route.dependant.query_params:
            assert re.search(r"\b" + re.escape(param.name) + r"\b", documented[key]), (key, param.name)


def test_mcp_reference_covers_tools_and_arguments(tmp_path):
    documented = sections(DOCS / "reference/mcp.md")

    async def schemas():
        async with Client(build_server(str(tmp_path))) as client:
            return (await client.list_tools()).tools

    actual = {tool.name: tool.input_schema for tool in asyncio.run(schemas())}
    assert documented.keys() == actual.keys()
    for name, schema in actual.items():
        for argument in schema.get("properties", {}):
            assert re.search(r"`" + re.escape(argument) + r"(?:`|=)", documented[name]), (name, argument)


def test_python_reference_targets_are_importable():
    # Resolve each explicitly documented object, catching stale names without mkdocs.
    import importlib

    page = (DOCS / "reference/python.md").read_text(encoding="utf-8")
    for target in re.findall(r"^::: ([\w.]+)$", page, re.M):
        parts = target.split(".")
        obj = importlib.import_module(target) if len(parts) == 2 else getattr(
            importlib.import_module(".".join(parts[:-1])), parts[-1])
        assert inspect.getdoc(obj), target
