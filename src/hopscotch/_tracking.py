"""PostHog analytics tracking for hopscotch-analytics."""
import json
import os
import pathlib
import platform
import sys
import uuid

_KEY  = "phc_sev8i3cCtComzsYJJ7KLfYYMqUCSAS49bVep8mkyoKYn"
_HOST = "https://eu.i.posthog.com"
_CONFIG = pathlib.Path.home() / ".hopscotch" / "config.json"

try:
    from posthog import Posthog
    _ph = Posthog(project_api_key=_KEY, host=_HOST)
except Exception:
    _ph = None  # type: ignore[assignment]


# ── distinct_id ────────────────────────────────────────────────────────────────

def _distinct_id() -> tuple[str, str]:
    """Return (distinct_id, id_type)."""
    # 1. /etc/machine-id — Linux (systemd), stable even in most containers
    try:
        mid = pathlib.Path("/etc/machine-id").read_text().strip()
        if mid:
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, mid)), "machine-id"
    except Exception:
        pass
    # 2. MAC address — macOS, Windows, Linux without /etc/machine-id
    try:
        node = uuid.getnode()
        # Real MAC address has the multicast bit unset
        if not (node >> 40) & 1:
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(node))), "mac-address"
    except Exception:
        pass
    # 3. Saved random UUID — Colab VMs, Docker, anything else
    try:
        _CONFIG.parent.mkdir(parents=True, exist_ok=True)
        if _CONFIG.exists():
            data = json.loads(_CONFIG.read_text())
            if did := data.get("distinct_id"):
                return did, "saved-uuid"
        did = str(uuid.uuid4())
        existing = json.loads(_CONFIG.read_text()) if _CONFIG.exists() else {}
        existing["distinct_id"] = did
        _CONFIG.write_text(json.dumps(existing))
        return did, "saved-uuid"
    except Exception:
        return "anonymous", "anonymous"


# ── environment detection ──────────────────────────────────────────────────────

def _detect_env() -> str:
    if "google.colab" in sys.modules or os.environ.get("COLAB_BACKEND_VERSION"):
        return "colab"
    try:
        shell = get_ipython().__class__.__name__  # type: ignore[name-defined]
        if "ZMQInteractiveShell" in shell:
            if os.environ.get("VSCODE_PID") or os.environ.get("VSCODE_INJECTION"):
                return "vscode"
            return "jupyter"
    except NameError:
        pass
    return "script"


def _kernel_id() -> str | None:
    try:
        import ipykernel
        conn = ipykernel.get_connection_file()
        basename = pathlib.Path(conn).stem  # e.g. "kernel-abc123"
        return basename.replace("kernel-", "")
    except Exception:
        return None


# ── cached base properties ─────────────────────────────────────────────────────

def _lib_version() -> str:
    try:
        from importlib.metadata import version
        return version("hopscotch-analytics")
    except Exception:
        return "unknown"


_DISTINCT_ID, _DISTINCT_ID_TYPE = _distinct_id()

_BASE_PROPS: dict = {
    "lib_version":      _lib_version(),
    "os":               platform.system(),
    "os_version":       platform.release(),
    "python_version":   platform.python_version(),
    "env":              _detect_env(),
    "distinct_id_type": _DISTINCT_ID_TYPE,
}

_kernel = _kernel_id()
if _kernel:
    _BASE_PROPS["kernel_id"] = _kernel


# ── opt-out ────────────────────────────────────────────────────────────────────

def _no_track_requested() -> bool:
    if os.environ.get("HOPSCOTCH_NO_TRACK"):
        return True
    try:
        from google.colab import userdata  # type: ignore[import]
        # Raises SecretNotFoundError for users without the secret — no popup shown.
        if userdata.get("HOPSCOTCH_NO_TRACK"):
            return True
    except Exception:
        pass
    return False


# ── public API ─────────────────────────────────────────────────────────────────

def track(event: str, properties: dict | None = None) -> None:
    """Fire-and-forget PostHog event. Never raises."""
    if _ph is None or _no_track_requested():
        return
    props = {**_BASE_PROPS, **(properties or {})}
    try:
        _ph.capture(distinct_id=_DISTINCT_ID, event=event, properties=props)
    except Exception:
        pass
