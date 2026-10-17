"""Build-only helpers: include tested examples, render argparse help, ship schema."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

from mkdocs.structure.files import File

ROOT = Path(__file__).resolve().parents[1]


def cli_sections(parser):
    """Yield help for the root command and every nested subcommand."""
    yield f"## `{parser.prog}`\n\n```text\n{parser.format_help().rstrip()}\n```\n"
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                yield from cli_sections(child)


def on_page_markdown(markdown, **kwargs):
    def include(match):
        relative = match.group(1)
        source = (ROOT / relative).resolve()
        if not source.is_relative_to(ROOT / "examples"):
            raise ValueError(f"example include outside examples/: {relative}")
        return "```python\n" + source.read_text(encoding="utf-8").rstrip() + "\n```"

    markdown = re.sub(r"<!-- hx:include (examples/[\w/.-]+\.py) -->", include, markdown)
    if "<!-- hx:cli -->" in markdown:
        from hx.cli import _build_parser
        markdown = markdown.replace("<!-- hx:cli -->", "\n".join(cli_sections(_build_parser())))
    return markdown


def on_files(files, config):
    files.append(File.generated(config, "reference/hx-4.schema.json",
                                content=(ROOT / "hx/schema/hx-4.schema.json").read_text(encoding="utf-8")))
    return files
