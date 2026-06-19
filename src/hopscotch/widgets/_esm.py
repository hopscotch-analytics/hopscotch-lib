"""Resolve the widget.js bundle path for anywidget.

Priority:
1. Local file next to the installed package (dev mode or already cached)
2. Download from the GitHub Release asset and cache at
   ~/.cache/hopscotch/widget-<version>.js  (avoids browser MIME-type issues
   with GitHub Release asset URLs served as application/octet-stream)
"""
import pathlib

_STATIC = pathlib.Path(__file__).parent.parent / "static"
_CDN_URL = (
    "https://github.com/hopscotch-analytics/hopscotch-lib"
    "/releases/download/v{version}/widget.js"
)


def _get_esm() -> pathlib.Path:
    local = _STATIC / "widget.js"
    if local.exists():
        return local

    try:
        from importlib.metadata import version as pkg_version
        v = pkg_version("hopscotch")
    except Exception:
        v = "latest"

    cache = pathlib.Path.home() / ".cache" / "hopscotch" / f"widget-{v}.js"
    if cache.exists():
        return cache

    try:
        import urllib.request
        url = _CDN_URL.format(version=v)
        cache.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, cache)
        return cache
    except Exception:
        # Last resort: return the URL and let anywidget try
        return pathlib.Path(_CDN_URL.format(version=v))
