import json
import pathlib
import threading

import anywidget
import traitlets

_STATIC = pathlib.Path(__file__).parent.parent / "static"
_UNSET = object()

from hopscotch.widgets._esm import _get_esm  # noqa: E402
from hopscotch.widgets import cloud as _cloud  # noqa: E402

try:
    from hopscotch._tracking import track as _track
except Exception:
    def _track(event, properties=None): pass  # type: ignore[misc]


class TransitionGraphWidget(anywidget.AnyWidget):
    _esm = _get_esm()
    _css = _STATIC / "widget.css"

    # ── recompute triggers ────────────────────────────────────────────────────
    values      = traitlets.Unicode("proba_out").tag(sync=True)
    diff        = traitlets.Unicode("").tag(sync=True)   # "" | '["col","v1","v2"]'
    path_id_col = traitlets.Unicode("").tag(sync=True)   # "" means schema default

    # ── read-only catalogues ──────────────────────────────────────────────────
    path_cols      = traitlets.Unicode("[]").tag(sync=True)
    event_counts    = traitlets.Unicode("{}").tag(sync=True)   # {event: count} full stream
    event_counts_g1 = traitlets.Unicode("{}").tag(sync=True)   # group1 counts (diff mode)
    event_counts_g2 = traitlets.Unicode("{}").tag(sync=True)   # group2 counts (diff mode)
    segment_levels = traitlets.Unicode("{}").tag(sync=True)

    # ── computed result ───────────────────────────────────────────────────────
    result     = traitlets.Unicode("{}").tag(sync=True)
    is_loading = traitlets.Bool(False).tag(sync=True)
    error      = traitlets.Unicode("").tag(sync=True)

    # ── widget type (used by the shared JS bundle to pick the right component) ─
    widget_type  = traitlets.Unicode("transition_graph").tag(sync=True)


    # ── event visibility (hidden/pinned per event) ────────────────────────────
    event_visibility = traitlets.Unicode("{}").tag(sync=True)  # JSON {id: {isHidden, isPinned}}

    # ── cloud ─────────────────────────────────────────────────────────────────
    auth_token          = traitlets.Unicode("").tag(sync=True)
    cloud_status        = traitlets.Unicode("idle").tag(sync=True)
    cloud_load_trigger  = traitlets.Int(0).tag(sync=True)
    cloud_save_request  = traitlets.Unicode("").tag(sync=True)
    cloud_auth_shown    = traitlets.Int(0).tag(sync=True)
    cloud_name_check    = traitlets.Unicode("").tag(sync=True)
    cloud_name_exists   = traitlets.Bool(False).tag(sync=True)
    cloud_load_warning  = traitlets.Unicode("").tag(sync=True)

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
        cloud_file_name: str | None = None,
        edge_weight=_UNSET,
        diff=_UNSET,
        path_id_col=_UNSET,
        height=_UNSET,
        sidebar_open=_UNSET,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._eventstream = eventstream
        self._initialized = False
        self._cloud_file_name = cloud_file_name
        self._cloud_save_timer: threading.Timer | None = None
        self._loading_from_cloud = False
        self._cloud_load_success = False
        self.widget_id = cloud_file_name or ""

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

        self.values       = edge_weight if edge_weight is not _UNSET else "proba_out"
        _diff_val         = diff         if diff         is not _UNSET else None
        self.diff         = json.dumps(list(_diff_val)) if _diff_val else ""
        self.path_id_col  = path_id_col  if path_id_col  is not _UNSET else ""
        self.height       = height       if height       is not _UNSET else 500
        self.sidebar_open = sidebar_open if sidebar_open is not _UNSET else True
        self.node_positions = "{}"

        # If cloud_file_name is set, defer recompute until cloud load succeeds
        if not self._cloud_file_name:
            self._recompute()

        self._initialized = True
        self.observe(self._on_params_change,         names=["values", "diff", "path_id_col"])
        self.observe(self._on_positions_change,      names=["node_positions"])
        self.observe(self._on_event_visibility_change, names=["event_visibility"])
        self.observe(self._on_compute_request,       names=["compute_request"])
        self.observe(self._on_cloud_load_trigger,    names=["cloud_load_trigger"])
        self.observe(self._on_cloud_save_request,    names=["cloud_save_request"])
        self.observe(self._on_cloud_auth_shown,      names=["cloud_auth_shown"])
        self.observe(self._on_cloud_name_check,      names=["cloud_name_check"])
        self.observe(self._on_auth_token,            names=["auth_token"])

    # ── observers ─────────────────────────────────────────────────────────────

    def _on_params_change(self, _change):
        if not self._initialized or self._loading_from_cloud:
            return
        self._recompute()
        if self._cloud_file_name and self.auth_token and self._cloud_load_success:
            self._schedule_cloud_save()

    def _on_positions_change(self, _change):
        if not self._initialized or self._loading_from_cloud:
            return
        if self._cloud_file_name and self.auth_token and self._cloud_load_success:
            self._schedule_cloud_save()

    def _on_event_visibility_change(self, _change):
        if not self._initialized or self._loading_from_cloud:
            return
        if self._cloud_file_name and self.auth_token and self._cloud_load_success:
            self._schedule_cloud_save()

    def _on_cloud_load_trigger(self, change):
        if change["new"] == 0:
            return
        if not self._cloud_file_name or not self.auth_token:
            return
        self._load_from_cloud()

    def _on_cloud_name_check(self, change):
        name = change["new"]
        if not name or not self.auth_token:
            return
        try:
            self.cloud_name_exists = _cloud.exists(self.auth_token, name)
        except Exception:
            self.cloud_name_exists = False

    def _on_cloud_save_request(self, change):
        name = change["new"]
        if not name or not self.auth_token:
            return
        self._cloud_file_name = name
        self.widget_id = name
        self._save_to_cloud()
        self.cloud_save_request = ""  # clear after handling

    def _on_cloud_auth_shown(self, change):
        if change["new"] == 0:
            return
        _track("cloud_auth_shown")

    def _on_auth_token(self, change):
        token = change["new"]
        if not token:
            return
        try:
            import base64 as _b64
            import json as _json
            part = token.split(".")[1]
            part += "=" * (4 - len(part) % 4)
            payload = _json.loads(_b64.urlsafe_b64decode(part))
            email = payload.get("email", "")
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

    # ── cloud ─────────────────────────────────────────────────────────────────

    def _load_from_cloud(self):
        self.cloud_status = "loading"
        self._loading_from_cloud = True
        try:
            state = _cloud.load(self.auth_token, self._cloud_file_name)
            if state:
                self._apply_state(state)
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
            _cloud.save(self.auth_token, self._cloud_file_name, "Transition Graph", self._current_state())
            self.cloud_status = "saved"
        except Exception as exc:
            self.cloud_status = f"error:{exc}"

    def _schedule_cloud_save(self):
        if self._cloud_save_timer:
            self._cloud_save_timer.cancel()
        self._cloud_save_timer = threading.Timer(1.0, self._save_to_cloud)
        self._cloud_save_timer.daemon = True
        self._cloud_save_timer.start()

    def _current_state(self) -> dict:
        return {
            "eventstream_id":   self._eventstream.fingerprint,
            "params": {
                "values":      self.values,
                "diff":        self.diff,
                "path_id_col": self.path_id_col,
            },
            "display": {
                "height":       self.height,
                "sidebar_open": self.sidebar_open,
            },
            "node_positions":  json.loads(self.node_positions or "{}"),
            "event_visibility": json.loads(self.event_visibility or "{}"),
        }

    def _apply_state(self, state: dict) -> None:
        p = state.get("params", {})
        d = state.get("display", {})
        es = self._eventstream
        reset = False

        self.values = p.get("values", "proba_out")

        # diff — apply only if segment column still exists
        _diff = _parse_diff(p.get("diff", ""))
        if _diff and _diff[0] not in es.schema.segment_cols:
            _diff = None; reset = True
        self.diff = json.dumps(list(_diff)) if _diff else ""

        # path_id_col — apply only if column still exists
        _pid = p.get("path_id_col") or ""
        if _pid and _pid not in es.schema.path_cols:
            _pid = ""; reset = True
        self.path_id_col = _pid
        self.height       = d.get("height", 500)
        self.sidebar_open = d.get("sidebar_open", True)
        pos = state.get("node_positions", {})
        self.node_positions = json.dumps(pos) if pos else "{}"
        ev = state.get("event_visibility", {})
        self.event_visibility = json.dumps(ev) if ev else "{}"
        saved_id = state.get("eventstream_id", "")
        current_id = self._eventstream.fingerprint
        mismatch = bool(saved_id and current_id and saved_id != current_id)
        if mismatch or reset:
            self.cloud_load_warning = (
                "This configuration was saved for a different eventstream. "
                "Some settings may not apply correctly."
            )
        else:
            self.cloud_load_warning = ""
        self._recompute()

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
        if tool == "transition_graph_data":
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
            diff_list = _parse_diff(self.diff)
            result = self._compute_tm_raw(
                values=self.values,
                path_id_col=self.path_id_col or None,
                diff=diff_list,
            )
            self.result = json.dumps(result)

            # Per-group event counts for diff mode
            if diff_list:
                try:
                    s1, s2 = self._eventstream.split_two(diff_list, path_id_col=self.path_id_col or None)
                    c1 = s1.get_event_counts()
                    c2 = s2.get_event_counts()
                    # path_start/path_end are synthetic and filtered out by split_two;
                    # their count equals the number of paths in each group
                    pid = self.path_id_col or s1.schema.path_cols[0]
                    for counts, s in ((c1, s1), (c2, s2)):
                        n = int(s.df[pid].nunique())
                        counts.setdefault("path_start", n)
                        counts.setdefault("path_end", n)
                    self.event_counts_g1 = json.dumps(c1)
                    self.event_counts_g2 = json.dumps(c2)
                except Exception:
                    self.event_counts_g1 = "{}"
                    self.event_counts_g2 = "{}"
            else:
                self.event_counts_g1 = "{}"
                self.event_counts_g2 = "{}"
        except Exception as exc:
            self.error = str(exc)
            self.result = "{}"
        finally:
            self.is_loading = False

    def _compute_tm_raw(self, values: str, path_id_col=None, diff=None) -> dict:
        tm = self._eventstream.transition_graph_data(
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
