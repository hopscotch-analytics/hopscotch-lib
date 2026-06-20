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


class ClusterAnalysisWidget(anywidget.AnyWidget):
    _esm = _get_esm()
    _css = _STATIC / "widget.css"

    widget_type = traitlets.Unicode("cluster_analysis").tag(sync=True)

    # ── config ─────────────────────────────────────────────────────────────
    features       = traitlets.Unicode("[]").tag(sync=True)   # JSON list of metric configs
    method         = traitlets.Unicode("kmeans").tag(sync=True)
    scaler         = traitlets.Unicode("minmax").tag(sync=True)
    n_clusters     = traitlets.Unicode("").tag(sync=True)      # "" | "3" | "3-8" | "[3,4,5]"
    nmf_k          = traitlets.Unicode("").tag(sync=True)      # "" | "3" | "3,5,7"
    nmf_enabled    = traitlets.Bool(False).tag(sync=True)
    metrics_config = traitlets.Unicode("[]").tag(sync=True)
    aggregation    = traitlets.Unicode("mean").tag(sync=True)
    path_id_col    = traitlets.Unicode("").tag(sync=True)
    apply_trigger  = traitlets.Unicode("").tag(sync=True)

    # ── catalogues ─────────────────────────────────────────────────────────
    event_list     = traitlets.Unicode("[]").tag(sync=True)
    path_cols      = traitlets.Unicode("[]").tag(sync=True)
    segment_cols   = traitlets.Unicode("[]").tag(sync=True)
    segment_levels = traitlets.Unicode("{}").tag(sync=True)

    # ── result ─────────────────────────────────────────────────────────────
    result     = traitlets.Unicode("{}").tag(sync=True)
    is_loading = traitlets.Bool(False).tag(sync=True)
    error      = traitlets.Unicode("").tag(sync=True)

    # ── display ────────────────────────────────────────────────────────────
    widget_id    = traitlets.Unicode("").tag(sync=True)
    height       = traitlets.Int(520).tag(sync=True)
    sidebar_open = traitlets.Bool(True).tag(sync=True)

    def __init__(
        self,
        eventstream,
        object_name: str | None = None,
        load_from: str | None = None,
        features=_UNSET,
        method=_UNSET,
        scaler=_UNSET,
        n_clusters=_UNSET,
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
        self.widget_type = "cluster_analysis"

        # Catalogues
        try:
            all_events = sorted(eventstream.df[eventstream.schema.event_col].astype(str).unique().tolist())
            self.event_list = json.dumps(all_events)
        except Exception:
            self.event_list = "[]"
        self.path_cols      = json.dumps(eventstream.schema.path_cols)
        self.segment_cols   = json.dumps(eventstream.schema.segment_cols)
        try:
            self.segment_levels = json.dumps(eventstream.get_all_segment_levels())
        except Exception:
            self.segment_levels = "{}"

        saved = _load_state(self._load_path)
        p = saved.get("params", {})
        d = saved.get("display", {})

        _feat = features if features is not _UNSET else p.get("features", None)
        if _feat is None:
            # Default: single event_count feature with all events as a list
            try:
                all_events = json.loads(self.event_list)
                _feat = [{"metric": "event_count", "metric_args": {"event": all_events}}]
            except Exception:
                _feat = []
        self.features       = json.dumps(_feat) if isinstance(_feat, list) else (_feat or "[]")
        self.method         = method         if method         is not _UNSET else p.get("method",      "kmeans")
        self.scaler         = scaler         if scaler         is not _UNSET else p.get("scaler",      "minmax")
        _nc = n_clusters if n_clusters is not _UNSET else p.get("n_clusters", "")
        self.n_clusters     = json.dumps(_nc) if isinstance(_nc, list) else (str(_nc) if _nc else "3-8")
        self.nmf_enabled    = p.get("nmf_enabled", False)
        self.nmf_k          = p.get("nmf_k", "")
        _mc = metrics_config if metrics_config is not _UNSET else p.get("metrics_config", None)
        if _mc is None:
            try:
                all_events = json.loads(self.event_list)
                _mc = [{"metric": "event_count", "metric_args": {"event": all_events}, "agg": "mean"}]
            except Exception:
                _mc = []
        self.metrics_config = json.dumps(_mc) if isinstance(_mc, list) else (_mc or "[]")
        self.aggregation    = p.get("aggregation", "mean")
        self.path_id_col    = path_id_col    if path_id_col    is not _UNSET else p.get("path_id_col", "")
        self.height         = height         if height         is not _UNSET else d.get("height",       520)
        self.sidebar_open   = sidebar_open   if sidebar_open   is not _UNSET else d.get("sidebar_open", True)

        self._initialized = True
        if self._save_path:
            self._save_state()

        self.observe(self._on_apply, names=["apply_trigger"])

    # ── observers ──────────────────────────────────────────────────────────

    def _on_apply(self, _change):
        if not self._initialized:
            return
        self._recompute()
        if self._save_path:
            self._schedule_save()

    # ── computation ────────────────────────────────────────────────────────

    def _recompute(self):
        self.is_loading = True
        self.error = ""
        try:
            features = json.loads(self.features) if self.features else []
            if not features:
                self.result = "{}"
                return
            metrics = json.loads(self.metrics_config) if self.metrics_config else []
            agg = self.aggregation or "mean"
            # Apply global aggregation to metrics that don't have their own agg
            metrics = [{**m, "agg": m.get("agg") or agg} for m in metrics]
            n_clusters = _parse_n_clusters(self.n_clusters)
            nmf_k = _parse_n_clusters(self.nmf_k) if self.nmf_enabled and self.nmf_k else None
            pid = self.path_id_col or None

            raw = self._eventstream.cluster_analysis_matrix(
                features=features,
                method=self.method,
                scaler=self.scaler or None,
                n_clusters=n_clusters,
                nmf_k=nmf_k,
                metrics_config=metrics,
                path_id_col=pid,
            )

            result: dict = {}
            if "overview_df" in raw and raw["overview_df"] is not None:
                df = raw["overview_df"]
                result["overview"] = {
                    "metrics":  df.index.tolist(),
                    "segments": df.columns.tolist(),
                    "values":   [[_safe(v) for v in df.loc[m].tolist()] for m in df.index],
                }
            if "silhouette" in raw:
                sil = raw["silhouette"]
                result["silhouette"] = {
                    "params":     sil["params"],
                    "silhouette": [_safe(s) for s in sil["silhouette"]],
                }
            if "nmf" in raw and raw["nmf"] is not None:
                result["nmf"] = raw["nmf"]

            self.result = json.dumps(result)
        except Exception as exc:
            self.error = str(exc)
            self.result = "{}"
        finally:
            self.is_loading = False

    # ── persistence ────────────────────────────────────────────────────────

    def _save_state(self):
        if not self._save_path:
            return
        try:
            self._save_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "version":  _STATE_VERSION,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "params": {
                    "features":       json.loads(self.features) if self.features else [],
                    "method":         self.method,
                    "scaler":         self.scaler,
                    "n_clusters":     self.n_clusters,
                    "nmf_enabled":    self.nmf_enabled,
                    "nmf_k":          self.nmf_k,
                    "metrics_config": json.loads(self.metrics_config) if self.metrics_config else [],
                    "aggregation":    self.aggregation,
                    "path_id_col":    self.path_id_col,
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

def _safe(v):
    import math
    if v is None:
        return None
    try:
        # Convert numpy scalars to Python native types
        if hasattr(v, "item"):
            v = v.item()
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
    except Exception:
        return None
    return v


def _parse_n_clusters(raw: str):
    if not raw or raw.strip() == "":
        return None
    s = raw.strip()
    try:
        # Range notation: "3-8" → [3,4,5,6,7,8]
        if "-" in s and not s.startswith("[") and not s.startswith("-"):
            parts = s.split("-")
            if len(parts) == 2:
                lo, hi = int(parts[0].strip()), int(parts[1].strip())
                return list(range(lo, hi + 1))
        # JSON list: "[3,4,5]"
        if s.startswith("["):
            return json.loads(s)
        # Comma-separated: "3,4,5"
        if "," in s:
            return [int(x.strip()) for x in s.split(",")]
        return int(s)
    except Exception:
        return None


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
