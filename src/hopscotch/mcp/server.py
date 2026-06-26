"""
hopscotch MCP server.

Usage in a Jupyter notebook:
    from hopscotch.mcp import serve
    serve(stream)
    serve(stream, context={"description": "...", "events": {...}})
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import threading
from typing import Any

import pandas as pd
from mcp.server.fastmcp import FastMCP

if False:
    from hopscotch.eventstream.eventstream import Eventstream


def serve(
    stream: "Eventstream",
    context: dict | None = None,
    port: int = 8765,
) -> None:
    """
    Start a local MCP server exposing *stream* to Claude (or any MCP client).

    Parameters
    ----------
    stream:
        The prepared Eventstream to analyse.
    context:
        Optional semantic layer — descriptions of events, segments, KPIs, etc.
        Example::

            serve(stream, context={
                "description": "E-commerce store. Main KPI — purchase conversion.",
                "events": {"basket": "Added to cart", "purchase": "Completed purchase"},
            })
    port:
        HTTP port for the SSE transport (default 8765).
    """
    mcp = _build_server(stream, context or {}, port=port, notebook_dir=os.getcwd())
    thread = threading.Thread(
        target=lambda: mcp.run(transport="sse"),
        daemon=True,
    )
    thread.start()
    print(
        f"hopscotch MCP server running on port {port}.\n"
        f"Add to Claude Desktop config:\n"
        f'  "hopscotch": {{"url": "http://localhost:{port}/sse"}}'
    )


# ── server builder ─────────────────────────────────────────────────────────────

def _build_server(
    stream: "Eventstream",
    context: dict,
    port: int = 8765,
    notebook_dir: str = "",
) -> FastMCP:
    from hopscotch.widgets._html_export import write_report_html

    mcp = FastMCP(
        "hopscotch",
        instructions=_system_instructions(stream, context, notebook_dir=notebook_dir),
        port=port,
    )

    # Report builder state — accumulates widgets across add_* calls,
    # reset by export_report.
    _pending: list[dict] = []

    @mcp.tool()
    def describe() -> str:
        """Return schema, event list, unique path counts and available segments."""
        s = stream.schema
        ec, pc = s.event_col, s.path_col
        df = stream.df
        result = {
            "n_paths":        int(df[pc].nunique()),
            "n_events_total": len(df),
            "event_col":      ec,
            "path_col":       pc,
            "path_cols":      s.path_cols,
            "segment_cols":   s.segment_cols,
            "events":         sorted(df[ec].astype(str).unique().tolist()),
        }
        if context.get("events"):
            result["event_descriptions"] = context["events"]
        if context.get("segments"):
            result["segment_descriptions"] = context["segments"]
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def add_transition_graph(
        label: str,
        edge_weight: str = "proba_out",
        diff: list | None = None,
        path_id_col: str | None = None,
    ) -> str:
        """
        Compute a transition graph and register it as a tab in the pending report.
        Returns the transition matrix so you can analyse it before writing the report.

        Call this (possibly multiple times with different parameters) before
        calling export_report().

        Parameters
        ----------
        label:
            Tab label shown in the report. Use a short descriptive name,
            e.g. "Overall Flow" or "Mobile vs Desktop". No colons in the label.
        edge_weight:
            How to weight edges. One of: proba_out, proba_in, count, unique_paths,
            transition_rate, per_path, time_median, time_q95.
        diff:
            Optional diff: [segment_col, value1, value2].
        path_id_col:
            Override the path ID column.

        Returns
        -------
        JSON with tab_id, events list, values matrix (and group1/group2 in diff mode).
        Use tab_id to reference this tab in the analysis text as [label:event].
        """
        widget = stream.transition_graph(edge_weight=edge_weight, diff=diff,
                                         path_id_col=path_id_col or None)
        if widget.error:
            return json.dumps({"error": widget.error, "label": label})
        data = {
            "widget_type":      "transition_graph",
            "result":           json.loads(widget.result or "{}"),
            "edge_weight":      widget.edge_weight,
            "diff":             json.loads(widget.diff) if widget.diff else None,
            "event_counts":     json.loads(widget.event_counts or "{}"),
            "event_counts_g1":  json.loads(widget.event_counts_g1 or "{}"),
            "event_counts_g2":  json.loads(widget.event_counts_g2 or "{}"),
            "node_positions":   {},
            "event_visibility": {},
            "segment_levels":   json.loads(widget.segment_levels or "{}"),
            "path_cols":        json.loads(widget.path_cols or "[]"),
            "path_id_col":      widget.path_id_col or "",
            "height":           widget.height,
            "sidebar_open":     False,
        }
        tab_id = f"tab-{len(_pending)}"
        _pending.append({"label": label, "data": data})

        # Return matrix data for Claude to analyse
        result_raw = json.loads(widget.result or "{}")
        out: dict = {
            "tab_id":  tab_id,
            "label":   label,
            "events":  result_raw.get("events", []),
            "values":  result_raw.get("values", []),
        }
        if result_raw.get("group1"):
            out["group1"] = result_raw["group1"]
            out["group2"] = result_raw["group2"]
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool()
    def add_step_matrix(
        label: str,
        max_steps: int = 10,
        diff: list | None = None,
        path_pattern: str | None = None,
        path_id_col: str | None = None,
    ) -> str:
        """
        Compute a step matrix and register it as a tab in the pending report.
        Returns the matrix data so you can analyse it before writing the report.

        Call this (possibly multiple times) before calling export_report().

        Parameters
        ----------
        label:
            Tab label shown in the report. No colons in the label.
        max_steps:
            Maximum steps before/after anchor.
        diff:
            Optional diff: [segment_col, value1, value2].
        path_pattern:
            Filter paths, e.g. "add_to_cart->.*->purchase".
        path_id_col:
            Override the path ID column.

        Returns
        -------
        JSON with tab_id, matrices list, event_counts.
        """
        widget = stream.step_matrix(
            max_steps=max_steps, diff=diff,
            path_id_col=path_id_col or None,
            path_pattern=path_pattern or None,
        )
        if widget.error:
            return json.dumps({"error": widget.error, "label": label})
        data = {
            "widget_type":    "step_matrix",
            "result":         json.loads(widget.result or "{}"),
            "max_steps":      widget.max_steps,
            "diff":           json.loads(widget.diff) if widget.diff else None,
            "path_id_col":    widget.path_id_col or "",
            "path_pattern":   widget.path_pattern or "",
            "path_cols":      json.loads(widget.path_cols or "[]"),
            "segment_levels": json.loads(widget.segment_levels or "{}"),
            "event_list":     json.loads(widget.event_list or "[]"),
            "height":         widget.height,
            "sidebar_open":   False,
            "display_prefs":  "{}",
        }
        tab_id = f"tab-{len(_pending)}"
        _pending.append({"label": label, "data": data})

        result_raw = json.loads(widget.result or "{}")
        return json.dumps({
            "tab_id":        tab_id,
            "label":         label,
            "matrices":      result_raw.get("matrices", []),
            "event_counts":  result_raw.get("event_counts", {}),
        }, ensure_ascii=False)

    @mcp.tool()
    def add_segment_overview(
        label: str,
        segment_col: str,
        metrics_config: list | None = None,
        path_id_col: str | None = None,
    ) -> str:
        """
        Compute a segment overview and register it as a tab in the pending report.
        Returns the overview table so you can analyse it before writing the report.

        Call this (possibly multiple times with different segment columns) before
        calling export_report().

        Parameters
        ----------
        label:
            Tab label shown in the report. No colons in the label.
        segment_col:
            Column to segment by (must be listed in segment_cols from describe()).
        metrics_config:
            List of additional metric dicts. segment_size and segment_share are
            always computed automatically and do not need to be specified.

            Each dict: {"metric": <name>, "metric_args": {...}, "agg": <agg>}
            "agg" choices: "mean" (default), "median", "complement_diff",
                           "q5", "q25", "q75", "q95"

            Available metrics and their metric_args:
              {"metric": "length"}
                  — number of events per path
              {"metric": "duration"}
                  — duration in seconds (first to last event)
              {"metric": "event_count", "metric_args": {"events": "purchase"}}
                  — how many times the event occurred; events can also be a list
              {"metric": "has", "metric_args": {"events": "purchase"}}
                  — 0/1 whether the path contains the event (conversion rate)
              {"metric": "time_between",
               "metric_args": {"event_from": "add_to_cart", "event_to": "purchase"}}
                  — seconds between first occurrences of two events
              {"metric": "matches",
               "metric_args": {"pattern": "add_to_cart->.*->purchase"}}
                  — 0/1 whether path matches the pattern

            Examples:
              Conversion rate to purchase by platform:
                metrics_config=[
                  {"metric": "has",  "metric_args": {"events": "purchase"}, "agg": "mean"},
                  {"metric": "length"},
                  {"metric": "duration", "agg": "median"},
                ]
              Time-to-purchase by acquisition channel:
                metrics_config=[
                  {"metric": "time_between",
                   "metric_args": {"event_from": "home", "event_to": "purchase"},
                   "agg": "median"},
                ]
        path_id_col:
            Override the path ID column.

        Returns
        -------
        JSON with tab_id, metrics list, segments list, values matrix.
        """
        widget = stream.segment_overview(
            segment_col=segment_col,
            metrics_config=metrics_config or [],
            path_id_col=path_id_col or None,
        )
        if widget.error:
            return json.dumps({"error": widget.error, "label": label})
        data = {
            "widget_type":    "segment_overview",
            "result":         json.loads(widget.result or "{}"),
            "segment_col":    widget.segment_col or "",
            "path_id_col":    widget.path_id_col or "",
            "metrics_config": json.loads(widget.metrics_config or "[]"),
            "segment_cols":   json.loads(widget.segment_cols or "[]"),
            "segment_levels": json.loads(widget.segment_levels or "{}"),
            "path_cols":      json.loads(widget.path_cols or "[]"),
            "event_list":     json.loads(widget.event_list or "[]"),
            "height":         widget.height,
            "sidebar_open":   False,
        }
        tab_id = f"tab-{len(_pending)}"
        _pending.append({"label": label, "data": data})

        result_raw = json.loads(widget.result or "{}")
        return json.dumps({
            "tab_id":   tab_id,
            "label":    label,
            "metrics":  result_raw.get("metrics", []),
            "segments": result_raw.get("segments", []),
            "values":   result_raw.get("values", []),
        }, ensure_ascii=False)

    @mcp.tool()
    def export_report(
        title: str = "Analysis Report",
        analysis: str | None = None,
        path: str | None = None,
    ) -> str:
        """
        Generate the HTML report with all widgets added via add_transition_graph /
        add_step_matrix. Resets the pending widget list afterwards.

        Parameters
        ----------
        title:
            Report title shown in the browser tab and as the heading.
        analysis:
            Full written analysis in markdown. Reference specific tabs and events
            with [tab_label:event_name] — clicking the link will activate that tab
            and focus the event. Use [event_name] (no label prefix) to focus in
            whichever tab is currently active.
            Example:
              "Drop-off at [Overall Flow:basket] is 45%. Timing shows
               [Timing:basket] takes 2.3 min on average. In the funnel
               [Purchase Funnel:payment_details] is the main bottleneck."
            Supports markdown: # headings, **bold**, *italic*, tables, - lists.
        path:
            Destination file path. If None, a temp file is created.
        """
        if not _pending:
            return json.dumps({"error": "No widgets added. Call add_transition_graph or add_step_matrix first."})

        if path is None:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".html", delete=False, prefix="hopscotch_"
            )
            path = tmp.name
            tmp.close()

        widgets = list(_pending)
        _pending.clear()

        write_report_html(path, title, widgets, analysis)
        return json.dumps({"path": str(pathlib.Path(path).resolve()), "title": title,
                           "tabs": [w["label"] for w in widgets]})

    return mcp


# ── helpers ────────────────────────────────────────────────────────────────────

def _df_to_matrix(df: Any) -> dict:
    return {
        "events":  df.index.tolist(),
        "columns": [int(c) for c in df.columns.tolist()],
        "values":  df.values.tolist(),
    }


def _df_to_list(df: Any) -> list:
    rows = []
    for _, row in df.iterrows():
        cells = []
        for v in row:
            if pd.isna(v):
                cells.append(None)
            elif isinstance(v, pd.Timedelta):
                cells.append(v.total_seconds())
            elif hasattr(v, "__float__"):
                cells.append(float(v))
            else:
                cells.append(v)
        rows.append(cells)
    return rows


def _system_instructions(stream: "Eventstream", context: dict, notebook_dir: str = "") -> str:
    s = stream.schema
    df = stream.df
    n_paths = int(df[s.path_col].nunique())
    events = sorted(df[s.event_col].astype(str).unique().tolist())

    lines = [
        "You are a product analytics assistant with access to a user behaviour eventstream.",
        f"The stream contains {n_paths} unique paths and {len(events)} distinct events.",
        f"Event column: '{s.event_col}'. Path column: '{s.path_col}'.",
    ]
    if context.get("description"):
        lines.append(f"Business context: {context['description']}")
    if context.get("events"):
        descs = ", ".join(f"'{k}': {v}" for k, v in context["events"].items())
        lines.append(f"Event meanings: {descs}")
    if context.get("kpis"):
        descs = ", ".join(f"'{k}': {v}" for k, v in context["kpis"].items())
        lines.append(f"Key metrics: {descs}")
    lines += [
        "",
        "## Workflow",
        "1. Call describe() to understand the data.",
        "2. Call add_transition_graph(), add_step_matrix(), and/or add_segment_overview() one or more times.",
        "   Each call computes a visualisation, returns its data for analysis,",
        "   and registers it as a tab (tab-0, tab-1, …) in the pending report.",
        "   You can add multiple visualisations of the same type with different",
        "   parameters (e.g. proba_out graph + time_median graph).",
        "3. Call export_report() with your full written analysis.",
        "   The HTML file will contain all added tabs and the analysis panel.",
        "",
        "## Analysis text",
        "- Use markdown: # Heading, ## Sub, **bold**, *italic*, - list, | table |.",
        "- Reference widgets using [tab_label:ref] syntax:",
        "    [Overall Flow:basket]               → focus node 'basket' in transition graph",
        "    [Overall Flow:basket->purchase]      → animate edge basket→purchase (marching ants)",
        "    [Purchase Funnel:basket@4]           → scroll to cell basket at step 4 in step matrix",
        "                                           (step_window expands automatically if needed)",
        "    [Platform Breakdown:mobile]            → highlight 'mobile' column in segment_overview",
        "                                             (displayed as 'platform: mobile' in report)",
        "    [Platform Breakdown:has_purchase@mobile] → highlight specific cell: metric@segment",
        "    [basket]                             → focus in whichever tab is currently active",
        "- Prefer edge links [tab:src->tgt] over node links when discussing transitions.",
        "- Use cell links [tab:event@step] when pointing to a specific step in the matrix.",
        "- Tab labels must not contain colons.",
        "- Always call export_report() and tell the user the file path.",
        f"- Save reports to the notebook directory: {notebook_dir}" if notebook_dir else
        "- Save reports to a convenient local path.",
    ]
    return "\n".join(lines)
