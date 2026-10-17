"""Optional external tools (simulators used ONLY as oracles; extraction never needs one). Every tool is listed in the
README's "Optional installations" table and resolved here, so a command that needs one and cannot find it fails with
the tool's name, its install hint and the override flag."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Optional

from .frontends.base import FrontendError


@dataclass(frozen=True)
class Tool:
    key: str
    name: str
    executable: str
    purpose: str
    install: str
    url: str
    flag: str
    fallbacks: tuple[str, ...] = ()
    env: str = ""


TOOLS: dict[str, Tool] = {t.key: t for t in (
    Tool("ngspice", "ngspice", "ngspice", "the ngspice oracle (`hx netlist check --oracle ngspice`)",
         "sudo apt-get install -y ngspice", "https://ngspice.sourceforge.io/download.html", "--ngspice", (), "HX_TOOL_NGSPICE"),
    Tool("xyce", "Xyce", "Xyce", "the Xyce syntax/topology oracle", "download the installer or build from source",
         "https://xyce.sandia.gov/downloads/", "--xyce", ("/usr/cad/xyce/parallel/bin/Xyce", "/usr/local/Xyce/bin/Xyce"), "HX_TOOL_XYCE"),
    Tool("xdm", "XDM", "xdm_bdl", "the XDM Xyce structural check",
         "download the xdm_bdl bundle from the XDM releases and put it on PATH", "https://github.com/Xyce/XDM/releases", "--xdm",
         ("~/.local/bin/xdm_bdl",), "HX_TOOL_XDM"),
    Tool("spectre", "Spectre", "spectre", "the Spectre syntax check (Phase N3)", "Cadence licensed install; put `spectre` on PATH",
         "https://www.cadence.com/", "--spectre", (), "HX_TOOL_SPECTRE"),
    Tool("hspice", "HSPICE", "hspice", "the HSPICE syntax check (Phase N3)", "Synopsys licensed install; put `hspice` on PATH",
         "https://www.synopsys.com/", "--hspice", (), "HX_TOOL_HSPICE"),
)}


def find_tool(key: str, override: Optional[str] = None) -> Optional[str]:
    """Path of the executable: explicit override → environment → PATH → known fallback locations; None when absent."""
    t = TOOLS[key]
    if override:                                   # an explicit path is the user's decision: never fall back from it
        p = shutil.which(override) or (os.path.expanduser(override) if os.path.isfile(os.path.expanduser(override)) else None)
        return p
    if t.env and os.environ.get(t.env):
        cand = os.environ[t.env]
        p = shutil.which(cand) or (os.path.expanduser(cand) if os.path.isfile(os.path.expanduser(cand)) else None)
        if p:
            return p
    p = shutil.which(t.executable)
    if p:
        return p
    for fb in t.fallbacks:
        fb = os.path.expanduser(fb)
        if os.path.isfile(fb):
            return fb
    return None


def resolve_tool(key: str, override: Optional[str] = None) -> str:
    """The executable, or a FrontendError that NAMES the tool, how to install it and the override flag."""
    p = find_tool(key, override)
    if p:
        return p
    t = TOOLS[key]
    raise FrontendError(f"{t.name} executable {override or t.executable!r} not found (needed for {t.purpose}); "
                        f"install it ({t.install}, {t.url}) or pass {t.flag} PATH")
