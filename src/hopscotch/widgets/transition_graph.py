import json
import pathlib
import threading
from datetime import datetime, timezone

import anywidget
import traitlets

_STATIC = pathlib.Path(__file__).parent.parent / "static"
_STATE_VERSION = 1
_UNSET = object()  # sentinel: distinguishes "not provided" from an explicit value

_CDN_URL = "https://github.com/hopscotch-analytics/hopscotch-lib/releases/download/v{version}/widget.js"

def _get_esm() -> "str | pathlib.Path":
    """Dev: use local bundle if it exists. Installed package: fetch from CDN."""
    local = _STATIC / "widget.js"
    if local.exists():
        return local
    try:
        from importlib.metadata import version
        return _CDN_URL.format(version=version("hopscotch"))
    except Exception:
        return _CDN_URL.format(version="latest")


class TransitionGraphWidget(anywidget.AnyWidget):
    _esm = _get_esm()
    _css = _STATIC / "widget.css"

    # ── recompute triggers ────────────────────────────────────────────────────
    values      = traitlets.Unicode("proba_out").tag(sync=True)
    diff        = traitlets.Unicode("").tag(sync=True)   # "" | '["col","v1","v2"]'
    path_id_col = traitlets.Unicode("").tag(sync=True)   # "" means schema default

    # ── read-only catalogues ──────────────────────────────────────────────────
    path_cols      = traitlets.Unicode("[]").tag(sync=True)
    event_counts   = traitlets.Unicode("{}").tag(sync=True)   # {event: count}
    segment_levels = traitlets.Unicode("{}").tag(sync=True)

    # ── computed result ───────────────────────────────────────────────────────
    result     = traitlets.Unicode("{}").tag(sync=True)
    is_loading = traitlets.Bool(False).tag(sync=True)
    error      = traitlets.Unicode("").tag(sync=True)

    # ── widget type (used by the shared JS bundle to pick the right component) ─
    widget_type  = traitlets.Unicode("transition_graph").tag(sync=True)

    # ── display / layout ──────────────────────────────────────────────────────
    # widget_id is passed to JS for unique localStorage keys
    widget_id    = traitlets.Unicode("").tag(sync=True)
    height       = traitlets.Int(500).tag(sync=True)
    sidebar_open = traitlets.Bool(True).tag(sync=True)

    # ── persistent graph state ────────────────────────────────────────────────
    # JS pushes positions here on every drag-end; Python saves to file.
    node_positions = traitlets.Unicode("{}").tag(sync=True)

    # ── generic compute protocol ──────────────────────────────────────────────
    compute_request  = traitlets.Unicode("").tag(sync=True)
    compute_response = traitlets.Unicode("").tag(sync=True)

    # ─────────────────────────────────────────────────────────────────────────

    def __init__(
        self,
        eventstream,
        object_name: str | None = None,
        load_from: str | None = None,
        values=_UNSET,
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
        self._save_path, self._load_path, _wid = _resolve_storage(object_name, load_from)
        self.widget_id = _wid

        # Catalogues
        try:
            self.segment_levels = json.dumps(eventstream.get_all_segment_levels())
        except Exception:
            self.segment_levels = "{}"
        self.path_cols = json.dumps(eventstream.schema.path_cols)
        try:
            self.event_counts = json.dumps(eventstream.get_event_counts())
        except Exception:
            self.event_counts = "{}"

        saved = self._load_state() if self._load_path else {}

        # Explicit constructor args have priority; saved state fills gaps.
        p = saved.get("params", {})
        d = saved.get("display", {})
        self.values       = values       if values       is not _UNSET else p.get("values",        "proba_out")
        _diff_val         = diff         if diff         is not _UNSET else _parse_diff(p.get("diff", ""))
        self.diff         = json.dumps(list(_diff_val)) if _diff_val else ""
        self.path_id_col  = path_id_col  if path_id_col  is not _UNSET else (p.get("path_id_col") or "")
        self.height       = height       if height       is not _UNSET else d.get("height",        500)
        self.sidebar_open = sidebar_open if sidebar_open is not _UNSET else d.get("sidebar_open",  True)

        # Positions from file → JS will use them as initialPositions prop
        self.node_positions = json.dumps(saved.get("node_positions", {}))

        # Initial compute
        self._recompute()

        self._initialized = True
        self.observe(self._on_params_change, names=["values", "diff", "path_id_col"])
        self.observe(self._on_positions_change, names=["node_positions"])
        self.observe(self._on_compute_request, names=["compute_request"])

    # ── persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        if self._load_path and self._load_path.exists():
            try:
                return json.loads(self._load_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_state(self):
        if not self._save_path:
            return
        try:
            self._save_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "version": _STATE_VERSION,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "params": {
                    "values": self.values,
                    "diff": self.diff,
                    "path_id_col": self.path_id_col,
                },
                "display": {
                    "height": self.height,
                    "sidebar_open": self.sidebar_open,
                },
                "node_positions": json.loads(self.node_positions or "{}"),
            }
            self._save_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _schedule_save(self):
        """Debounce file writes — save 1 s after the last change."""
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(1.0, self._save_state)
        self._save_timer.daemon = True
        self._save_timer.start()

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
        if tool == "transition_matrix":
            return self._compute_tm_raw(
                values=params.get("values", self.values),
                path_id_col=params.get("path_id_col") or self.path_id_col or None,
                diff=_parse_diff(params.get("diff")),
            )
        if tool == "graph_layout":
            return self._compute_graph_layout(params)
        raise ValueError(f"Unknown tool: {tool!r}")

    # ── computations ──────────────────────────────────────────────────────────

    def _recompute(self):
        self.is_loading = True
        self.error = ""
        try:
            result = self._compute_tm_raw(
                values=self.values,
                path_id_col=self.path_id_col or None,
                diff=_parse_diff(self.diff),
            )
            self.result = json.dumps(result)
        except Exception as exc:
            self.error = str(exc)
            self.result = "{}"
        finally:
            self.is_loading = False

    def _compute_tm_raw(self, values: str, path_id_col=None, diff=None) -> dict:
        tm = self._eventstream.transition_matrix(
            values=values,
            path_id_col=path_id_col,
            diff=diff,
        )
        if diff is not None:
            tm, tm1, tm2 = tm
            return {
                "events": tm.index.tolist(),
                "values": _df_to_list(tm),
                "group1": {"events": tm1.index.tolist(), "values": _df_to_list(tm1)},
                "group2": {"events": tm2.index.tolist(), "values": _df_to_list(tm2)},
            }
        return {"events": tm.index.tolist(), "values": _df_to_list(tm)}

    def _compute_graph_layout(self, params: dict) -> dict:
        try:
            from hopscotch.tools.graph_layout import GraphLayout  # type: ignore
            result = GraphLayout(self._eventstream).fit(
                sample_size=params.get("sample_size", 1000),
                embedding_dim=params.get("embedding_dim", 32),
                n_clusters=params.get("n_clusters", 5),
                random_state=params.get("random_state", 42),
            )
            return {"result": result}
        except Exception:
            return {"result": {}}


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_storage(
    object_name: str | None,
    load_from: str | None,
) -> tuple[pathlib.Path | None, pathlib.Path | None, str]:
    """Return (save_path, load_path, widget_id).

    object_name="foo"              → save + load: .hopscotch/foo.json  widget_id="foo"
    load_from="./bar.json"         → load only from ./bar.json          widget_id="bar"
    object_name + load_from        → load from load_from, save to .hopscotch/{name}.json
    neither                        → no persistence
    """
    save_path: pathlib.Path | None = None
    load_path: pathlib.Path | None = None
    widget_id = ""

    if object_name:
        save_path = pathlib.Path(".hopscotch") / f"{object_name}.json"
        load_path = save_path
        widget_id = object_name

    if load_from:
        load_path = pathlib.Path(load_from)
        if not widget_id:
            widget_id = load_path.stem

    return save_path, load_path, widget_id


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


def _df_to_list(df) -> list:
    import pandas as pd
    rows = []
    for _, row in df.iterrows():
        cells = []
        for v in row:
            if isinstance(v, pd.Timedelta):
                cells.append(None if pd.isna(v) else v.total_seconds())
            elif hasattr(v, "__float__"):
                cells.append(float(v))
            else:
                cells.append(None)
        rows.append(cells)
    return rows
