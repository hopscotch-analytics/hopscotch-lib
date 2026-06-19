"""Resolve the widget.js bundle for anywidget.

Priority:
1. Local file (dev mode — widget.js built next to the package).
2. Download the JS source from the GitHub Release asset and return it as a
   string.  anywidget creates a blob URL with Content-Type: text/javascript
   from a plain string, bypassing the MIME-type issue that occurs when the
   browser does import() directly on a GitHub asset URL
   (served as application/octet-stream).
"""
import pathlib

_STATIC = pathlib.Path(__file__).parent.parent / "static"
_CDN_URL = (
    "https://github.com/hopscotch-analytics/hopscotch-lib"
    "/releases/download/v{version}/widget.js"
)


def _get_esm() -> "pathlib.Path | str":
    local = _STATIC / "widget.js"
    if local.exists():
        return local

    try:
        from importlib.metadata import version as pkg_version
        v = pkg_version("hopscotch")
    except Exception:
        v = "latest"

    import urllib.request
    url = _CDN_URL.format(version=v)
    with urllib.request.urlopen(url) as resp:
        return resp.read().decode("utf-8")
