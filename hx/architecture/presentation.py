"""Offline HTML presentation of an interpreted architecture document."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from .model import ArchitectureDocument, ArchitectureError

ASSETS = Path(__file__).parent
VENDOR = ASSETS.parent / "viewer" / "vendor"


def payload(doc: ArchitectureDocument, code_url: str | None = None) -> dict:
    """Attach navigation URLs without changing authored bindings or identities."""
    if code_url:
        parsed = urlsplit(code_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.fragment:
            raise ArchitectureError("--code-url must be an absolute http(s) viewer URL without a fragment")
    data = doc.to_dict()
    data["code_urls"] = {identity: code_url + "#" + urlencode({"kind": "node", "sel": binding["symbol"]})
                         for identity, binding in doc.bindings.items()
                         if code_url and binding["status"] == "resolved"}
    return data


def build_html(doc: ArchitectureDocument | None = None, *, code_url: str | None = None,
               _elk_source: str | None = None) -> str:
    """Build a standalone diagram, or a served page that loads /api/architecture.

    Source text is never embedded. Exported code links need an explicit viewer URL.
    The private source override supports the pre-promotion layout experiment.
    """
    template = (ASSETS / "index.html").read_text(encoding="utf-8")
    data = payload(doc, code_url) if doc else None
    script_data = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    elk = _elk_source if _elk_source is not None else (VENDOR / "elk.bundled.js").read_text(encoding="utf-8")
    js = (ASSETS / "diagram.js").read_text(encoding="utf-8")
    license_text = (VENDOR / "elk-LICENSE.md").read_text(encoding="utf-8") if _elk_source is None else "elkjs: EPL-2.0 OR GPL-3.0-or-later; https://github.com/kieler/elkjs"
    notice = '<script type="text/plain" id="hx-elk-license">' + license_text.replace("</script", "<\\/script") + "</script>"
    return template.replace("/*HX:DATA*/null", script_data).replace("/*HX:ELK*/", elk.replace("</script", "<\\/script")).replace("/*HX:SCRIPT*/", js.replace("</script", "<\\/script")).replace("</body>", notice + "</body>")
