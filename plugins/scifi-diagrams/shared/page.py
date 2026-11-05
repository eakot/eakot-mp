"""One self-contained HTML page: theme, fonts (as data URIs), the diagram's CSS and JS, and its data inline.

Shared by every skill in scifi-diagrams. Python 3.9+, standard library only. A page makes no network request.
"""
from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path

SHARED = Path(__file__).resolve().parent

#: http(s), or a same-origin path. A protocol-relative `//host/…` leaves the origin, so it is not "relative" here.
SAFE_URL = re.compile(r"^(https?://|/(?!/)|\./|\.\./|#)", re.I)


def _no_constant(name: str) -> float:
    raise ValueError(f"{name} is not a number in JSON; leave a missing number out")


def load_json(path: str | Path) -> object:
    """JSON as the browser's JSON.parse reads it: NaN and Infinity are refused, not passed through."""
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_no_constant)


def theme_css() -> str:
    """The shared theme with every `url(fonts/…)` replaced by its bytes."""
    css = (SHARED / "theme.css").read_text(encoding="utf-8")

    def inline(m: re.Match) -> str:
        font = SHARED / "fonts" / m.group(1)
        return "url(data:font/woff2;base64," + base64.b64encode(font.read_bytes()).decode("ascii") + ")"

    return re.sub(r"url\(fonts/([\w.-]+\.woff2)\)", inline, css)


def json_script(data: object, element_id: str) -> str:
    """JSON in a <script> element that no string inside it can close early."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    text = text.replace("<", "\\u003c")    # no "</script", no "<!--", no "<script" survives
    return f'<script type="application/json" id="{element_id}">{text}</script>'


def page(title: str, css: list[str], js: list[str], body: str, boot: str, data: object, data_id: str) -> str:
    favicon = base64.b64encode((SHARED / "favicon.svg").read_bytes()).decode("ascii")
    styles = "\n".join([theme_css(), *css])
    scripts = "\n".join(f"<script>{s}</script>" for s in js)
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)}</title>"
        f"<link rel=\"icon\" href=\"data:image/svg+xml;base64,{favicon}\">"
        f"<style>{styles}</style></head>\n<body class=\"sd-page\">{body}\n"
        f"{json_script(data, data_id)}\n{scripts}\n<script>{boot}</script>\n</body></html>\n"
    )
