import json
import pathlib
import threading
from datetime import datetime, timezone

import anywidget
import traitlets

_STATIC = pathlib.Path(__file__).parent.parent / "static"
_STATE_VERSION = 1
_UNSET = object()

from hopscotch.widgets._esm import _get_esm  # noqa: E402


class FunnelWidget(anywidget.AnyWidget):
    _esm = _get_esm()
    _css = _STATIC / "widget.css"

    widget_type = traitlets.Unicode("funnel").tag(sync=True)

    # ── recompute triggers ────────────────────────────────────────────────────
    steps       = traitlets.Unicode("[]").tag(sync=True)  # JSON list of event names
    diff        = traitlets.Unicode("").tag(sync=True)    # "" | '["col","v1","v2"]'
    path_id_col = traitlets.Unicode("").tag(sync=True)

    # ── catalogues ────────────────────────────────────────────────────────────
    event_list     = traitlets.Unicode("[]").tag(sync=True)   # sorted event names for picker
    path_cols      = traitlets.Unicode("[]").tag(sync=True)
    segment_levels = traitlets.Unicode("{}").tag(sync=True)

    # ── result ────────────────────────────────────────────────────────────────
    result     = traitlets.Unicode("{}").tag(sync=True)
    is_loading = traitlets.Bool(False).tag(sync=True)
    error      = traitlets.Unicode("").tag(sync=True)

    # ── display ───────────────────────────────────────────────────────────────
    widget_id    = traitlets.Unicode("").tag(sync=True)
    height       = traitlets.Int(420).tag(sync=True)
    sidebar_open = traitlets.Bool(True).tag(sync=True)

    # ─────────────────────────────────────────────────────────────────────────

    def __init__(
        self,
        eventstream,
        object_name: str | None = None,
        load_from: str | None = None,
        steps=_UNSET,
        diff=_UNSET,
        path_id_col=_UNSET,
        height=_UNSET,
        sidebar_open=_UNSET,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._eventstream = eventstream
        self._initialized = False
        self._save_timer: threading.Timer | None = None
        self._save_path, _wid = _resolve_storage(object_name, load_from)
        self._load_path = _resolve_load_path(object_name, load_from)
        self.widget_id = _wid
        self.widget_type = "funnel"

        # Catalogues
        try:
            all_events = sorted(
                eventstream.df[eventstream.schema.event_col].astype(str).unique().tolist()
            )
            self.event_list = json.dumps(all_events)
        except Exception:
            self.event_list = "[]"

        try:
            self.segment_levels = json.dumps(eventstream.get_all_segment_levels())
        except Exception:
            self.segment_levels = "{}"

        self.path_cols = json.dumps(eventstream.schema.path_cols)

        # Load saved state
        saved = _load_state(self._load_path)
        p = saved.get("params", {})
        d = saved.get("display", {})

        _steps_val = steps if steps is not _UNSET else p.get("steps", [])
        self.steps       = json.dumps(_steps_val) if isinstance(_steps_val, list) else (_steps_val or "[]")
        _diff_val        = diff if diff is not _UNSET else _parse_diff(p.get("diff", ""))
        self.diff        = json.dumps(list(_diff_val)) if _diff_val else ""
        self.path_id_col = path_id_col if path_id_col is not _UNSET else (p.get("path_id_col") or "")
        self.height      = height      if height      is not _UNSET else d.get("height",       420)
        self.sidebar_open = sidebar_open if sidebar_open is not _UNSET else d.get("sidebar_open", True)

        self._recompute()
        self._initialized = True

        if self._save_path:
            self._save_state()

        self.observe(self._on_params_change, names=["steps", "diff", "path_id_col"])

    # ── observers ─────────────────────────────────────────────────────────────

    def _on_params_change(self, _change):
        if not self._initialized:
            return
        self._recompute()
        if self._save_path:
            self._schedule_save()

    # ── computation ───────────────────────────────────────────────────────────

    def _recompute(self):
        self.is_loading = True
        self.error = ""
        try:
            steps = json.loads(self.steps) if self.steps else []
            diff  = _parse_diff(self.diff)
            pid   = self.path_id_col or None
            result = self._eventstream.funnel_matrix(steps=steps, diff=diff, path_id_col=pid)
            if diff and len(diff) == 3:
                result["group1_label"] = str(diff[1])
                result["group2_label"] = str(diff[2])
                # Include total paths per group (denominator for conversion rates)
                steps_list = result.get("steps", [])
                if steps_list:
                    r1 = steps_list[0].get("funnel1_conversion_rate") or 0
                    r2 = steps_list[0].get("funnel2_conversion_rate") or 0
                    up1 = steps_list[0].get("funnel1_unique_paths", 0)
                    up2 = steps_list[0].get("funnel2_unique_paths", 0)
                    result["group1_total"] = round(up1 / r1) if r1 > 0 else up1
                    result["group2_total"] = round(up2 / r2) if r2 > 0 else up2
            else:
                steps_list = result.get("steps", [])
                if steps_list:
                    r = steps_list[0].get("conversion_rate") or 0
                    up = steps_list[0].get("unique_paths", 0)
                    result["total_paths"] = round(up / r) if r > 0 else up
            self.result = json.dumps(result)
        except Exception as exc:
            self.error = str(exc)
            self.result = "{}"
        finally:
            self.is_loading = False

    # ── persistence ───────────────────────────────────────────────────────────

    def _save_state(self):
        if not self._save_path:
            return
        try:
            self._save_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "version": _STATE_VERSION,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "params": {
                    "steps":       json.loads(self.steps) if self.steps else [],
                    "diff":        self.diff,
                    "path_id_col": self.path_id_col,
                },
                "display": {
                    "height":       self.height,
                    "sidebar_open": self.sidebar_open,
                },
            }
            self._save_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _schedule_save(self):
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(1.0, self._save_state)
        self._save_timer.daemon = True
        self._save_timer.start()


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_storage(object_name, load_from):
    widget_id = ""
    save_path = None
    if object_name:
        save_path = pathlib.Path(".hopscotch") / f"{object_name}.json"
        widget_id = object_name
    if load_from and not widget_id:
        widget_id = pathlib.Path(load_from).stem
    return save_path, widget_id


def _resolve_load_path(object_name, load_from):
    if load_from:
        return pathlib.Path(load_from)
    if object_name:
        return pathlib.Path(".hopscotch") / f"{object_name}.json"
    return None


def _load_state(load_path):
    if load_path and load_path.exists():
        try:
            return json.loads(load_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


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
