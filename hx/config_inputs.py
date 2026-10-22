"""Configuration candidates shared by Rust extraction and project watching.

These are potential inputs, not a reimplementation of Cargo/rustup precedence.
Missing candidates matter: creating one can change the next extraction.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional


def rust_config_candidates(root: str) -> list[str]:
    """Return absolute candidate paths for tools launched from root.

    Probe the working directory and ancestors, plus Cargo home. Include legacy
    spellings and missing files, without walking home directories or reading
    credentials. Workspace-member configs are not selected from source paths.
    """
    cwd = Path(os.path.realpath(root))
    paths = set()
    for directory in (cwd, *cwd.parents):
        for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain", "rust-toolchain.toml",
                     ".cargo/config", ".cargo/config.toml"):
            paths.add(str(directory / name))
    home = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo").expanduser()
    if not home.is_absolute():
        home = cwd / home
    for name in ("config", "config.toml"):
        paths.add(os.path.abspath(home / name))
    return sorted(paths)


def snapshot_inputs(paths: Iterable[str]) -> dict[str, Optional[int]]:
    """Observe timestamps before indexing; None retains an absent candidate."""
    observed = {}
    for path in paths:
        try:
            observed[path] = os.stat(path).st_mtime_ns
        except OSError:
            observed[path] = None
    return observed
