"""Copy a tutorial fixture into a new workspace; run from a repository checkout."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
LANGUAGES = {"c": "c", "cpp": "cpp", "sv": "sv", "rust": "rust", "python": "python", "netlist": "spice/ota"}


def prepare(language: str, destination: Path) -> Path:
    """Create a fresh fixture copy and, for C/C++, its compilation database.

    The destination must not exist. No compiler or simulator is executed.
    """
    source = FIXTURES / LANGUAGES[language]
    destination = destination.expanduser().resolve()
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(
        ".hx", "__pycache__", "*.pyc", "target", "build", "obj_dir"))
    if language in {"c", "cpp"}:
        build = destination / "build"
        build.mkdir()
        suffix, compiler, standard = ("*.c", "gcc", "-std=c11") if language == "c" else ("*.cpp", "g++", "-std=c++17")
        commands = [{"directory": str(destination), "file": str(src.relative_to(destination)),
                     "arguments": [compiler, standard, "-Iinclude", "-Wall", "-O1", "-c",
                                   str(src.relative_to(destination)), "-o", f"build/{src.stem}.o"]}
                    for src in sorted((destination / "src").glob(suffix))]
        (build / "compile_commands.json").write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", choices=LANGUAGES)
    parser.add_argument("destination", type=Path, help="new directory; existing directories are never overwritten")
    args = parser.parse_args()
    try:
        print(prepare(args.language, args.destination))
    except FileExistsError:
        parser.error(f"destination already exists: {args.destination}; choose a new directory")


if __name__ == "__main__":
    main()
