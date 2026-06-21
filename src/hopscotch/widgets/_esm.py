"""Resolve the widget.js bundle for anywidget.

Priority:
1. Local file (dev mode — widget.js built next to the package).
2. Cached file in the static directory (downloaded on first use).
3. Download from GitHub Release asset, cache it, and return as string.
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
        v = pkg_version("hopscotch-analytics")
    except Exception:
        v = "latest"

    cache = _STATIC / f"widget-{v}.js"
    if cache.exists():
        return cache

    import urllib.request
    url = _CDN_URL.format(version=v)
    with urllib.request.urlopen(url) as resp:
        js = resp.read().decode("utf-8")

    try:
        cache.write_text(js, encoding="utf-8")
        return cache
    except Exception:
        return js
