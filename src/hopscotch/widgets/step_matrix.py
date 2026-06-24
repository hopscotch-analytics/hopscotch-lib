import json
import pathlib
import threading

import anywidget
import traitlets

_STATIC = pathlib.Path(__file__).parent.parent / "static"
_UNSET = object()

from hopscotch.widgets._esm import _get_esm   # noqa: E402
from hopscotch.widgets import cloud as _cloud  # noqa: E402

try:
    from hopscotch._tracking import track as _track
except Exception:
    def _track(event, properties=None): pass  # type: ignore[misc]


class StepMatrixWidget(anywidget.AnyWidget):
    _esm = _get_esm()
    _css = _STATIC / "widget.css"

    widget_type = traitlets.Unicode("step_matrix").tag(sync=True)

    # ── recompute triggers ────────────────────────────────────────────────────
    max_steps    = traitlets.Int(10).tag(sync=True)
    diff         = traitlets.Unicode("").tag(sync=True)
    path_id_col  = traitlets.Unicode("").tag(sync=True)
    path_pattern = traitlets.Unicode("").tag(sync=True)

    # ── catalogues ────────────────────────────────────────────────────────────
    event_list     = traitlets.Unicode("[]").tag(sync=True)
    path_cols      = traitlets.Unicode("[]").tag(sync=True)
    segment_levels = traitlets.Unicode("{}").tag(sync=True)

    # ── result ────────────────────────────────────────────────────────────────
    result     = traitlets.Unicode("{}").tag(sync=True)
    is_loading = traitlets.Bool(False).tag(sync=True)
    error      = traitlets.Unicode("").tag(sync=True)

    # ── cloud ─────────────────────────────────────────────────────────────────
    auth_token         = traitlets.Unicode("").tag(sync=True)
    cloud_status       = traitlets.Unicode("idle").tag(sync=True)
    cloud_load_trigger = traitlets.Int(0).tag(sync=True)
    cloud_save_request = traitlets.Unicode("").tag(sync=True)
    cloud_auth_shown   = traitlets.Int(0).tag(sync=True)
    cloud_name_check   = traitlets.Unicode("").tag(sync=True)
    cloud_name_exists  = traitlets.Bool(False).tag(sync=True)

    # ── display ───────────────────────────────────────────────────────────────
    widget_id     = traitlets.Unicode("").tag(sync=True)
    height        = traitlets.Int(600).tag(sync=True)
    sidebar_open  = traitlets.Bool(True).tag(sync=True)
    display_prefs = traitlets.Unicode("{}").tag(sync=True)

    def __init__(
        self,
        eventstream,
        cloud_file_name: str | None = None,
        max_steps=_UNSET,
        diff=_UNSET,
        path_id_col=_UNSET,
        path_pattern=_UNSET,
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
        self._cloud_load_success = False   # True only after successful cloud load
        self.widget_id = cloud_file_name or ""
        self.widget_type = "step_matrix"

        try:
            all_events = sorted(eventstream.df[eventstream.schema.event_col].astype(str).unique().tolist())
            self.event_list = json.dumps(all_events)
        except Exception:
            self.event_list = "[]"
        try:
            self.segment_levels = json.dumps(eventstream.get_all_segment_levels())
        except Exception:
            self.segment_levels = "{}"
        self.path_cols = json.dumps(eventstream.schema.path_cols)

        self.max_steps    = max_steps    if max_steps    is not _UNSET else 10
        _diff_val         = diff         if diff         is not _UNSET else None
        self.diff         = json.dumps(list(_diff_val)) if _diff_val else ""
        self.path_id_col  = path_id_col  if path_id_col  is not _UNSET else ""
        self.path_pattern = path_pattern if path_pattern is not _UNSET else ""
        self.height       = height       if height       is not _UNSET else 600
        self.sidebar_open = sidebar_open if sidebar_open is not _UNSET else True

        # If cloud_file_name is set, defer recompute until cloud load succeeds
        if not self._cloud_file_name:
            self._recompute()
        self._initialized = True

        self.observe(self._on_params_change,        names=["max_steps", "diff", "path_id_col", "path_pattern"])
        self.observe(self._on_display_prefs_change, names=["display_prefs"])
        self.observe(self._on_cloud_load_trigger,   names=["cloud_load_trigger"])
        self.observe(self._on_cloud_save_request,   names=["cloud_save_request"])
        self.observe(self._on_cloud_name_check,     names=["cloud_name_check"])
        self.observe(self._on_cloud_auth_shown,     names=["cloud_auth_shown"])
        self.observe(self._on_auth_token,           names=["auth_token"])

    # ── observers ─────────────────────────────────────────────────────────────

    def _on_params_change(self, _change):
        if not self._initialized or self._loading_from_cloud:
            return
        self._recompute()
        if self._cloud_file_name and self.auth_token and self._cloud_load_success:
            self._schedule_cloud_save()

    def _on_cloud_name_check(self, change):
        name = change["new"]
        if not name or not self.auth_token:
            return
        try:
            self.cloud_name_exists = _cloud.exists(self.auth_token, name)
        except Exception:
            self.cloud_name_exists = False

    def _on_display_prefs_change(self, _change):
        if not self._initialized or self._loading_from_cloud:
            return
        if self._cloud_file_name and self.auth_token and self._cloud_load_success:
            self._schedule_cloud_save()

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
            import base64 as _b64, json as _json
            part = token.split(".")[1]
            part += "=" * (4 - len(part) % 4)
            email = _json.loads(_b64.urlsafe_b64decode(part)).get("email", "")
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

    # ── computation ───────────────────────────────────────────────────────────

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

    def _compute_raw(self, max_steps, path_id_col=None, diff=None, path_pattern=None) -> dict:
        raw = self._eventstream.step_sankey_data(
            max_steps=max_steps,
            diff=diff,
            path_id_col=path_id_col,
            path_pattern=path_pattern,
        )
        if diff is not None:
            diff_sms, sms1, sms2 = raw
            matrices = [_df_to_matrix(sm) for sm in diff_sms]
            g1 = [_df_to_matrix(sm) for sm in sms1]
            g2 = [_df_to_matrix(sm) for sm in sms2]
            for i, m in enumerate(matrices):
                m["group1"] = g1[i]
                m["group2"] = g2[i]
        else:
            matrices = [_df_to_matrix(sm) for sm in raw]
            for m in matrices:
                m["group1"] = None
                m["group2"] = None

        try:
            pid = path_id_col or self._eventstream.schema.path_col
            ec  = self._eventstream.schema.event_col
            import duckdb
            df  = self._eventstream._df
            event_counts = (
                duckdb.sql(f"SELECT {ec}, COUNT(DISTINCT {pid}) AS cnt FROM df GROUP BY {ec}")
                .df().set_index(ec)["cnt"].to_dict()
            )
            event_counts = {str(k): int(v) for k, v in event_counts.items()}
            total_paths = int(duckdb.sql(f"SELECT COUNT(DISTINCT {pid}) FROM df").fetchone()[0])
            for synthetic in ("path_start", "path_end"):
                if synthetic not in event_counts:
                    event_counts[synthetic] = total_paths
        except Exception:
            event_counts = {}

        event_counts_g1: dict = {}
        event_counts_g2: dict = {}
        if diff is not None:
            try:
                import duckdb as _duckdb
                _pid = path_id_col or self._eventstream.schema.path_col
                _ec  = self._eventstream.schema.event_col
                _df  = self._eventstream._df
                _seg_col, _val1, _val2 = diff

                for _val, _target in [(_val1, "event_counts_g1"), (_val2, "event_counts_g2")]:
                    _d = _df[_df[_seg_col] == _val]
                    _c = (_duckdb.sql(
                        f"SELECT {_ec}, COUNT(DISTINCT {_pid}) AS cnt FROM _d GROUP BY {_ec}"
                    ).df().set_index(_ec)["cnt"].to_dict())
                    _c = {str(k): int(v) for k, v in _c.items()}
                    _tot = int(_duckdb.sql(
                        f"SELECT COUNT(DISTINCT {_pid}) FROM _d"
                    ).fetchone()[0])
                    for _syn in ("path_start", "path_end"):
                        if _syn not in _c:
                            _c[_syn] = _tot
                    if _target == "event_counts_g1":
                        event_counts_g1 = _c
                    else:
                        event_counts_g2 = _c
            except Exception:
                pass

        return {"matrices": matrices, "event_counts": event_counts,
                "event_counts_g1": event_counts_g1, "event_counts_g2": event_counts_g2}

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
            _cloud.save(self.auth_token, self._cloud_file_name, "Step Matrix", self._current_state())
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
            "params": {
                "max_steps":    self.max_steps,
                "diff":         self.diff,
                "path_id_col":  self.path_id_col,
                "path_pattern": self.path_pattern,
            },
            "display": {
                "height":        self.height,
                "sidebar_open":  self.sidebar_open,
                "display_prefs": self.display_prefs,
            },
        }

    def _apply_state(self, state: dict) -> None:
        p = state.get("params", {})
        d = state.get("display", {})
        self.max_steps    = p.get("max_steps", 10)
        _diff = _parse_diff(p.get("diff", ""))
        self.diff         = json.dumps(list(_diff)) if _diff else ""
        self.path_id_col  = p.get("path_id_col") or ""
        self.path_pattern = p.get("path_pattern") or ""
        self.height       = d.get("height", 600)
        self.sidebar_open = d.get("sidebar_open", True)
        self.display_prefs = d.get("display_prefs", "{}")
        self._recompute()


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
