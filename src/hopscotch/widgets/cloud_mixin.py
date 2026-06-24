"""Reusable cloud save/load mixin for anywidget widgets."""
from __future__ import annotations

import base64 as _b64
import json
import threading

import traitlets

from hopscotch.widgets import cloud as _cloud

try:
    from hopscotch._tracking import track as _track
except Exception:
    def _track(event, properties=None): pass  # type: ignore[misc]

_WARNING_MISMATCH = (
    "This configuration was saved for a different eventstream. "
    "Some settings may not apply correctly. "
    "Auto-save is disabled — save with a new name if you want to keep this configuration."
)


def _parse_diff(raw):
    if not raw:
        return None
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else list(raw)
        if isinstance(parsed, list) and len(parsed) == 3:
            return parsed
    except Exception:
        pass
    return None


class CloudMixin(traitlets.HasTraits):
    """
    Mixin for anywidget widgets that support cloud save/load of state.

    Subclass requirements
    ---------------------
    - Set ``self._eventstream`` before calling ``_init_cloud()``.
    - Set ``self._initialized = True`` after initial setup.
    - Implement ``_current_state() -> dict``.
    - Implement ``_apply_state(state: dict) -> None``
      (call ``_apply_base_state()`` to handle common fields).
    - Implement ``_recompute() -> None``.
    - Call ``self.observe(self._on_params_change, names=[...])``
      for widget-specific recompute triggers.
    """

    # ── Cloud traitlets ────────────────────────────────────────────────────────
    widget_id          = traitlets.Unicode("").tag(sync=True)
    display_prefs      = traitlets.Unicode("{}").tag(sync=True)
    auth_token         = traitlets.Unicode("").tag(sync=True)
    cloud_status       = traitlets.Unicode("idle").tag(sync=True)
    cloud_load_trigger = traitlets.Int(0).tag(sync=True)
    cloud_save_request = traitlets.Unicode("").tag(sync=True)
    cloud_auth_shown   = traitlets.Int(0).tag(sync=True)
    cloud_name_check   = traitlets.Unicode("").tag(sync=True)
    cloud_name_exists  = traitlets.Bool(False).tag(sync=True)
    cloud_load_warning = traitlets.Unicode("").tag(sync=True)

    # ── Init ──────────────────────────────────────────────────────────────────

    def _init_cloud(self, cloud_file_name: str | None) -> None:
        """Call from __init__ after self._eventstream is set."""
        self._cloud_file_name:   str | None            = cloud_file_name
        self._cloud_save_timer:  threading.Timer | None = None
        self._loading_from_cloud: bool = False
        self._cloud_load_success: bool = False
        self._cloud_load_mismatch: bool = False
        self.widget_id = cloud_file_name or ""

        self.observe(self._on_cloud_load_trigger,  names=["cloud_load_trigger"])
        self.observe(self._on_cloud_save_request,  names=["cloud_save_request"])
        self.observe(self._on_cloud_auth_shown,    names=["cloud_auth_shown"])
        self.observe(self._on_auth_token,          names=["auth_token"])
        self.observe(self._on_cloud_name_check,    names=["cloud_name_check"])
        self.observe(self._on_display_prefs_change, names=["display_prefs"])

    # ── Observers ─────────────────────────────────────────────────────────────

    def _on_cloud_load_trigger(self, change):
        if change["new"] == 0 or not self._cloud_file_name or not self.auth_token:
            return
        self._load_from_cloud()

    def _on_cloud_save_request(self, change):
        name = change["new"]
        if not name or not self.auth_token:
            return
        self._cloud_file_name = name
        self.widget_id = name
        self._save_to_cloud()
        self.cloud_save_request = ""

    def _on_cloud_auth_shown(self, change):
        if change["new"] == 0:
            return
        _track("cloud_auth_shown")

    def _on_auth_token(self, change):
        token = change["new"]
        if not token:
            return
        try:
            part = token.split(".")[1]
            part += "=" * (4 - len(part) % 4)
            email = json.loads(_b64.urlsafe_b64decode(part)).get("email", "")
            if email:
                _track("user_authenticated", {"email": email})
                try:
                    from hopscotch._tracking import _ph, _DISTINCT_ID
                    if _ph:
                        _ph.identify(_DISTINCT_ID, properties={"email": email})
                except Exception:
                    pass
        except Exception:
            pass

    def _on_cloud_name_check(self, change):
        name = change["new"]
        if not name or not self.auth_token:
            return
        try:
            self.cloud_name_exists = _cloud.exists(self.auth_token, name)
        except Exception:
            self.cloud_name_exists = False

    def _on_display_prefs_change(self, _change):
        if not self._initialized or self._loading_from_cloud:  # type: ignore[attr-defined]
            return
        if (self._cloud_file_name and self.auth_token
                and self._cloud_load_success and not self._cloud_load_mismatch):
            self._schedule_cloud_save()

    # ── Cloud I/O ─────────────────────────────────────────────────────────────

    def _load_from_cloud(self):
        self.cloud_status = "loading"
        self._loading_from_cloud = True
        try:
            state = _cloud.load(self.auth_token, self._cloud_file_name)
            if state:
                self._apply_state(state)  # type: ignore[attr-defined]
                self.cloud_status = "loaded"
                self._cloud_load_success = True
            else:
                self.cloud_status = "error:File not found"
        except Exception as exc:
            self.cloud_status = f"error:{exc}"
        finally:
            self._loading_from_cloud = False

    def _save_to_cloud(self):
        if not self._cloud_file_name or not self.auth_token:
            return
        self.cloud_status = "saving"
        try:
            _cloud.save(
                self.auth_token,
                self._cloud_file_name,
                self.widget_type,  # type: ignore[attr-defined]
                self._current_state(),  # type: ignore[attr-defined]
            )
            self.cloud_status = "saved"
        except Exception as exc:
            self.cloud_status = f"error:{exc}"

    def _schedule_cloud_save(self):
        if self._cloud_save_timer:
            self._cloud_save_timer.cancel()
        self._cloud_save_timer = threading.Timer(1.0, self._save_to_cloud)
        self._cloud_save_timer.daemon = True
        self._cloud_save_timer.start()

    # ── Shared state helpers ──────────────────────────────────────────────────

    def _base_state(self) -> dict:
        """Eventstream fingerprint — include in every _current_state()."""
        return {"eventstream_id": self._eventstream.fingerprint}  # type: ignore[attr-defined]

    def _apply_base_state(self, state: dict):
        """
        Validate and apply common cloud-state fields.

        Validates diff (resets if segment column gone) and path_id_col
        (resets if column gone).  Checks the eventstream fingerprint and
        sets cloud_load_warning / _cloud_load_mismatch accordingly.

        Returns
        -------
        (validated_diff, validated_pid, mismatch)
        """
        es = self._eventstream  # type: ignore[attr-defined]
        p = state.get("params", {})
        reset = False

        # diff — reset if segment column no longer exists
        _diff = _parse_diff(p.get("diff", ""))
        if _diff and _diff[0] not in es.schema.segment_cols:
            _diff = None
            reset = True

        # path_id_col — reset if column no longer exists
        _pid = p.get("path_id_col") or ""
        if _pid and _pid not in es.schema.path_cols:
            _pid = ""
            reset = True

        # fingerprint check
        saved_id   = state.get("eventstream_id", "")
        current_id = es.fingerprint
        mismatch   = bool(saved_id and current_id and saved_id != current_id)

        if mismatch or reset:
            self._cloud_load_mismatch = True
            self.cloud_load_warning = _WARNING_MISMATCH
        else:
            self._cloud_load_mismatch = False
            self.cloud_load_warning = ""

        return _diff, _pid, mismatch

    def _guard_auto_save(self) -> bool:
        """Return True if auto-save should proceed."""
        return bool(
            self._cloud_file_name
            and self.auth_token
            and self._cloud_load_success
            and not self._cloud_load_mismatch
        )
