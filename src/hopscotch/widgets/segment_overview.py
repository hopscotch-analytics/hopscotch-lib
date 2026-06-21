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


class SegmentOverviewWidget(anywidget.AnyWidget):
    _esm = _get_esm()
    _css = _STATIC / "widget.css"

    widget_type = traitlets.Unicode("segment_overview").tag(sync=True)

    # ── config traitlets ───────────────────────────────────────────────────
    segment_col    = traitlets.Unicode("").tag(sync=True)
    path_id_col    = traitlets.Unicode("").tag(sync=True)
    metrics_config = traitlets.Unicode("[]").tag(sync=True)  # JSON list
    apply_trigger  = traitlets.Unicode("").tag(sync=True)    # any change → recompute

    # ── catalogues ────────────────────────────────────────────────────────
    segment_cols   = traitlets.Unicode("[]").tag(sync=True)
    segment_levels = traitlets.Unicode("{}").tag(sync=True)
    path_cols    = traitlets.Unicode("[]").tag(sync=True)
    event_list   = traitlets.Unicode("[]").tag(sync=True)

    # ── result ────────────────────────────────────────────────────────────
    result     = traitlets.Unicode("{}").tag(sync=True)
    is_loading = traitlets.Bool(False).tag(sync=True)
    error      = traitlets.Unicode("").tag(sync=True)

    # ── distribution request/result ───────────────────────────────────────
    dist_request = traitlets.Unicode("").tag(sync=True)
    dist_result  = traitlets.Unicode("{}").tag(sync=True)

    # ── paywall ───────────────────────────────────────────────────────────────
    paywall_required = traitlets.Bool(False).tag(sync=True)

    # ── display ───────────────────────────────────────────────────────────
    widget_id    = traitlets.Unicode("").tag(sync=True)
    height       = traitlets.Int(480).tag(sync=True)
    sidebar_open = traitlets.Bool(True).tag(sync=True)

    def __init__(
        self,
        eventstream,
        object_name: str | None = None,
        load_from: str | None = None,
        segment_col=_UNSET,
        metrics_config=_UNSET,
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
        self.widget_type = "segment_overview"

        # Catalogues
        try:
            all_events = sorted(eventstream.df[eventstream.schema.event_col].astype(str).unique().tolist())
            self.event_list = json.dumps(all_events)
        except Exception:
            self.event_list = "[]"
        self.segment_cols = json.dumps(eventstream.schema.segment_cols)
        try:
            self.segment_levels = json.dumps(eventstream.get_all_segment_levels())
        except Exception:
            self.segment_levels = "{}"
        self.path_cols    = json.dumps(eventstream.schema.path_cols)

        # Paywall check
        try:
            n_paths = eventstream.df[eventstream.schema.path_cols[0]].nunique()
            self.paywall_required = n_paths > 1000
        except Exception:
            self.paywall_required = False

        saved = _load_state(self._load_path)
        p = saved.get("params", {})
        d = saved.get("display", {})

        self.segment_col    = segment_col    if segment_col    is not _UNSET else p.get("segment_col", "")
        self.path_id_col    = path_id_col    if path_id_col    is not _UNSET else p.get("path_id_col", "")
        _mc                 = metrics_config if metrics_config is not _UNSET else p.get("metrics_config", [])
        self.metrics_config = json.dumps(_mc) if isinstance(_mc, list) else (_mc or "[]")
        self.height         = height         if height         is not _UNSET else d.get("height",       480)
        self.sidebar_open   = sidebar_open   if sidebar_open   is not _UNSET else d.get("sidebar_open", True)

        if self.segment_col:
            self._recompute()

        self._initialized = True
        if self._save_path:
            self._save_state()

        self.observe(self._on_apply,        names=["apply_trigger"])
        self.observe(self._on_dist_request, names=["dist_request"])

    # ── observers ─────────────────────────────────────────────────────────

    def _on_apply(self, _change):
        if not self._initialized:
            return
        self._recompute()
        if self._save_path:
            self._schedule_save()

    def _on_dist_request(self, change):
        raw = change["new"]
        if not raw:
            return
        try:
            req = json.loads(raw)
        except Exception:
            return
        self._compute_distribution(req)

    # ── computation ───────────────────────────────────────────────────────

    def _recompute(self):
        self.is_loading = True
        self.error = ""
        try:
            metrics = json.loads(self.metrics_config) if self.metrics_config else []
            df = self._eventstream.segment_overview_matrix(
                segment_col=self.segment_col,
                metrics_config=metrics,
                path_id_col=self.path_id_col or None,
            )
            self.result = json.dumps({
                "metrics":  df.index.tolist(),
                "segments": df.columns.tolist(),
                "values":   [[_safe(v) for v in df.loc[m].tolist()] for m in df.index],
            })
        except Exception as exc:
            self.error = str(exc)
            self.result = "{}"
        finally:
            self.is_loading = False

    def _compute_distribution(self, req: dict):
        self.is_loading = True
        try:
            result = self._eventstream.metric_distribution(
                segment_col=req["segment_col"],
                segment_value=req["segment_value"],
                metric=req["metric"],
                complement=req.get("complement", False),
                path_id_col=req.get("path_id_col"),
            )
            self.dist_result = json.dumps(result, default=lambda x: None if (isinstance(x, float) and x != x) else x)
        except Exception as exc:
            self.dist_result = json.dumps({"error": str(exc)})
        finally:
            self.is_loading = False

    # ── persistence ───────────────────────────────────────────────────────

    def _save_state(self):
        if not self._save_path:
            return
        try:
            self._save_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "version":  _STATE_VERSION,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "params": {
                    "segment_col":    self.segment_col,
                    "path_id_col":    self.path_id_col,
                    "metrics_config": json.loads(self.metrics_config) if self.metrics_config else [],
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


def _safe(v):
    import math
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


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
