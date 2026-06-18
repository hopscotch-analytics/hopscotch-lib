import json
import pathlib
import threading
from datetime import datetime, timezone

import anywidget
import traitlets

_STATIC = pathlib.Path(__file__).parent.parent / "static"
_STATE_VERSION = 1
_UNSET = object()

_CDN_URL = "https://github.com/hopscotch-analytics/hopscotch-lib/releases/download/v{version}/widget.js"

def _get_esm() -> "str | pathlib.Path":
    local = _STATIC / "widget.js"
    if local.exists():
        return local
    try:
        from importlib.metadata import version
        return _CDN_URL.format(version=version("hopscotch"))
    except Exception:
        return _CDN_URL.format(version="latest")


class StepSankeyWidget(anywidget.AnyWidget):
    _esm = _get_esm()   # dev: local file; installed: CDN URL
    _css = _STATIC / "widget.css"

    widget_type  = traitlets.Unicode("step_sankey").tag(sync=True)

    # ── recompute triggers ────────────────────────────────────────────────────
    max_steps    = traitlets.Int(10).tag(sync=True)
    diff         = traitlets.Unicode("").tag(sync=True)   # "" | '["col","v1","v2"]'
    path_id_col  = traitlets.Unicode("").tag(sync=True)
    path_pattern = traitlets.Unicode("").tag(sync=True)   # "" | "path_start->.*->event->.*->path_end"

    # ── catalogues ────────────────────────────────────────────────────────────
    path_cols      = traitlets.Unicode("[]").tag(sync=True)
    segment_levels = traitlets.Unicode("{}").tag(sync=True)

    # ── result ────────────────────────────────────────────────────────────────
    result     = traitlets.Unicode("{}").tag(sync=True)
    is_loading = traitlets.Bool(False).tag(sync=True)
    error      = traitlets.Unicode("").tag(sync=True)

    # ── display ───────────────────────────────────────────────────────────────
    widget_id    = traitlets.Unicode("").tag(sync=True)
    height       = traitlets.Int(500).tag(sync=True)
    sidebar_open = traitlets.Bool(True).tag(sync=True)
    # 0 = use default (3); >0 = show only this many variable columns per anchor
    step_window  = traitlets.Int(0).tag(sync=True)

    # ── persistent state ──────────────────────────────────────────────────────
    node_positions = traitlets.Unicode("{}").tag(sync=True)

    # ── compute protocol ──────────────────────────────────────────────────────
    compute_request  = traitlets.Unicode("").tag(sync=True)
    compute_response = traitlets.Unicode("").tag(sync=True)

    # ─────────────────────────────────────────────────────────────────────────

    def __init__(
        self,
        eventstream,
        object_name: str | None = None,
        load_from: str | None = None,
        max_steps=_UNSET,
        diff=_UNSET,
        path_id_col=_UNSET,
        path_pattern=_UNSET,
        height=_UNSET,
        sidebar_open=_UNSET,
        step_window=_UNSET,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._eventstream = eventstream
        self._initialized = False
        self._save_timer: threading.Timer | None = None
        self._save_path, _wid = _resolve_object_dir(object_name, load_from)
        self._load_path = _resolve_load_path(object_name, load_from)
        self.widget_id = _wid

        # Catalogues
        try:
            self.segment_levels = json.dumps(eventstream.get_all_segment_levels())
        except Exception:
            self.segment_levels = "{}"
        self.path_cols = json.dumps(eventstream.schema.path_cols)

        # Load saved state
        saved = _load_state(self._load_path)
        p = saved.get("params", {})
        d = saved.get("display", {})

        self.max_steps    = max_steps    if max_steps    is not _UNSET else p.get("max_steps",    10)
        _diff_val         = diff         if diff         is not _UNSET else _parse_diff(p.get("diff", ""))
        self.diff         = json.dumps(list(_diff_val)) if _diff_val else ""
        self.path_id_col  = path_id_col  if path_id_col  is not _UNSET else (p.get("path_id_col") or "")
        self.path_pattern = path_pattern if path_pattern is not _UNSET else (p.get("path_pattern") or "")
        self.height       = height       if height       is not _UNSET else d.get("height",       500)
        self.sidebar_open = sidebar_open if sidebar_open is not _UNSET else d.get("sidebar_open",  True)
        self.step_window  = step_window  if step_window  is not _UNSET else d.get("step_window",   0)
        self.node_positions = json.dumps(saved.get("node_positions", {}))

        self._recompute()

        self._initialized = True
        self.observe(self._on_params_change, names=["max_steps", "diff", "path_id_col", "path_pattern"])
        self.observe(self._on_positions_change, names=["node_positions"])
        self.observe(self._on_compute_request, names=["compute_request"])

    # ── observers ─────────────────────────────────────────────────────────────

    def _on_params_change(self, _change):
        if not self._initialized:
            return
        self._recompute()
        if self._save_path:
            self._schedule_save()

    def _on_positions_change(self, _change):
        if not self._initialized:
            return
        if self._save_path:
            self._schedule_save()

    def _on_compute_request(self, change):
        raw = change["new"]
        if not raw:
            return
        try:
            req = json.loads(raw)
        except Exception:
            return
        req_id = req.get("id", "")
        tool   = req.get("tool", "")
        params = req.get("params", {})
        try:
            result = self._dispatch(tool, params)
            self.compute_response = json.dumps({"id": req_id, "result": result})
        except Exception as exc:
            self.compute_response = json.dumps({"id": req_id, "error": str(exc)})

    # ── dispatch ──────────────────────────────────────────────────────────────

    def _dispatch(self, tool: str, params: dict):
        if tool == "step_matrix":
            return self._compute_raw(
                max_steps=params.get("max_steps", self.max_steps),
                path_id_col=params.get("path_id_col") or self.path_id_col or None,
                diff=_parse_diff(params.get("diff")),
                path_pattern=params.get("path_pattern") or self.path_pattern or None,
            )
        raise ValueError(f"Unknown tool: {tool!r}")

    # ── computations ──────────────────────────────────────────────────────────

    def _recompute(self):
        self.is_loading = True
        self.error = ""
        try:
            result = self._compute_raw(
                max_steps=self.max_steps,
                path_id_col=self.path_id_col or None,
                diff=_parse_diff(self.diff),
                path_pattern=self.path_pattern or None,
            )
            self.result = json.dumps(result)
        except Exception as exc:
            self.error = str(exc)
            self.result = "{}"
        finally:
            self.is_loading = False

    def _compute_raw(self, max_steps: int, path_id_col=None, diff=None, path_pattern=None) -> dict:
        raw = self._eventstream.step_matrix(
            max_steps=max_steps,
            diff=diff,
            path_id_col=path_id_col,
            path_pattern=path_pattern,
        )

        if diff is not None:
            diff_sms, sms1, sms2 = raw
            matrices   = [_df_to_matrix(sm) for sm in diff_sms]
            group1_mats = [_df_to_matrix(sm) for sm in sms1]
            group2_mats = [_df_to_matrix(sm) for sm in sms2]
            for i, m in enumerate(matrices):
                m["group1"] = group1_mats[i]
                m["group2"] = group2_mats[i]
        else:
            matrices = [_df_to_matrix(sm) for sm in raw]
            for m in matrices:
                m["group1"] = None
                m["group2"] = None

        try:
            path_col = path_id_col or self._eventstream.schema.path_col
            event_col = self._eventstream.schema.event_col
            df = self._eventstream._df
            import duckdb
            counts = (
                duckdb.sql(
                    f"SELECT {event_col}, COUNT(DISTINCT {path_col}) AS cnt "
                    f"FROM df GROUP BY {event_col}"
                )
                .df()
                .set_index(event_col)["cnt"]
                .to_dict()
            )
            event_counts = {str(k): int(v) for k, v in counts.items()}
        except Exception:
            event_counts = {}

        return {"matrices": matrices, "event_counts": event_counts}

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
                    "max_steps":    self.max_steps,
                    "diff":         self.diff,
                    "path_id_col":  self.path_id_col,
                    "path_pattern": self.path_pattern,
                },
                "display": {
                    "height":       self.height,
                    "sidebar_open": self.sidebar_open,
                    "step_window":  self.step_window,
                },
                "node_positions": json.loads(self.node_positions or "{}"),
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

def _resolve_object_dir(object_name, load_from) -> tuple[pathlib.Path | None, str]:
    widget_id = ""
    save_path = None
    if object_name:
        save_path = pathlib.Path(".hopscotch") / f"{object_name}.json"
        widget_id = object_name
    if load_from and not widget_id:
        widget_id = pathlib.Path(load_from).stem
    return save_path, widget_id


def _resolve_load_path(object_name, load_from) -> pathlib.Path | None:
    if load_from:
        return pathlib.Path(load_from)
    if object_name:
        return pathlib.Path(".hopscotch") / f"{object_name}.json"
    return None


def _load_state(load_path: pathlib.Path | None) -> dict:
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


def _df_to_matrix(df) -> dict:
    return {
        "events":  df.index.tolist(),
        "values":  df.values.tolist(),
        "columns": [int(c) for c in df.columns.tolist()],
    }
