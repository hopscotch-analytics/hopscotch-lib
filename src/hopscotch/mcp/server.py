"""
hopscotch MCP server.

Usage in a Jupyter notebook:
    from hopscotch.mcp import serve
    serve(stream)
    serve(stream, context={"description": "...", "events": {...}})
"""
from __future__ import annotations

import json
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
    mcp = _build_server(stream, context or {}, port=port)
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

def _build_server(stream: "Eventstream", context: dict, port: int = 8765) -> FastMCP:
    mcp = FastMCP(
        "hopscotch",
        instructions=_system_instructions(stream, context),
        port=port,
    )

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
    def transition_graph_data(
        edge_weight: str = "proba_out",
        diff: list | None = None,
        path_id_col: str | None = None,
    ) -> str:
        """
        Compute transition probabilities between events.

        Parameters
        ----------
        edge_weight:
            How to weight edges. One of: proba_out, proba_in, count, unique_paths,
            transition_rate, per_path, time_median, time_q95.
        diff:
            Optional diff: [segment_col, value1, value2].
            Returns combined (value2 - value1), group1, group2 matrices.
        path_id_col:
            Override the path ID column.

        Returns
        -------
        JSON: events (list), values (N×N matrix). In diff mode also group1, group2.
        """
        result = stream.transition_graph_data(
            edge_weight=edge_weight,
            diff=diff,
            path_id_col=path_id_col or None,
        )
        if diff is not None:
            combined, g1, g2 = result
            return json.dumps({
                "events": combined.index.tolist(),
                "values": _df_to_list(combined),
                "group1": {"events": g1.index.tolist(), "values": _df_to_list(g1)},
                "group2": {"events": g2.index.tolist(), "values": _df_to_list(g2)},
                "diff":   diff,
            }, ensure_ascii=False)
        return json.dumps({
            "events": result.index.tolist(),
            "values": _df_to_list(result),
        }, ensure_ascii=False)

    @mcp.tool()
    def export_html(
        path: str | None = None,
        title: str = "Transition Graph",
        edge_weight: str = "proba_out",
        diff: list | None = None,
        analysis: str | None = None,
    ) -> str:
        """
        Render the transition graph as a standalone interactive HTML file.
        Returns the absolute path to the generated file.

        The HTML is self-contained (no server needed) — open in any browser,
        share, or embed in slides.

        Parameters
        ----------
        path:
            Destination file path. If None, a temp file is created.
        title:
            Title shown in the browser tab and as the report heading.
        edge_weight / diff:
            Same as transition_graph_data.
        analysis:
            Your written analysis of the graph. Wrap event names in square
            brackets to make them clickable links that focus the node, e.g.:
            "The biggest drop-off is at [basket] (78% of users leave here).
            Users who reach [purchase] typically came via [view]."
            Supports markdown: **bold**, *italic*, # headings, tables, - lists.
        """
        if path is None:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".html", delete=False, prefix="hopscotch_"
            )
            path = tmp.name
            tmp.close()

        widget = stream.transition_graph(edge_weight=edge_weight, diff=diff)
        widget.export_html(path, title=title, analysis=analysis)
        return json.dumps({"path": str(pathlib.Path(path).resolve()), "title": title})

    @mcp.tool()
    def step_matrix_data(
        max_steps: int = 10,
        diff: list | None = None,
        path_pattern: str | None = None,
        path_id_col: str | None = None,
    ) -> str:
        """
        Compute a step matrix: for each event, its frequency at each relative
        step position around an anchor.

        Parameters
        ----------
        max_steps:
            Maximum number of steps before/after anchor to include.
        diff:
            Optional diff: [segment_col, value1, value2].
        path_pattern:
            Filter to paths matching this pattern, e.g. "add_to_cart->.*->purchase".
        path_id_col:
            Override the path ID column.

        Returns
        -------
        JSON with matrices list (each has events, columns, values) and event_counts.
        """
        raw = stream.step_sankey_data(
            max_steps=max_steps,
            diff=diff,
            path_id_col=path_id_col or None,
            path_pattern=path_pattern or None,
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
        return json.dumps({"matrices": matrices}, ensure_ascii=False)

    @mcp.tool()
    def export_step_matrix_html(
        path: str | None = None,
        title: str = "Step Matrix",
        max_steps: int = 10,
        diff: list | None = None,
        path_pattern: str | None = None,
        analysis: str | None = None,
    ) -> str:
        """
        Render the step matrix as a standalone interactive HTML file.
        Returns the absolute path to the generated file.

        Parameters
        ----------
        path:
            Destination file path. If None, a temp file is created.
        title:
            Title shown in the browser tab and as the report heading.
        max_steps / diff / path_pattern:
            Same as step_matrix_data.
        analysis:
            Your written analysis. Wrap event names in [brackets] to make them
            clickable — they will scroll the matrix to that event row.
            Supports markdown: **bold**, *italic*, # headings, tables, - lists.
        """
        if path is None:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".html", delete=False, prefix="hopscotch_"
            )
            path = tmp.name
            tmp.close()

        widget = stream.step_matrix(
            max_steps=max_steps, diff=diff, path_pattern=path_pattern or None
        )
        widget.export_html(path, title=title, analysis=analysis)
        return json.dumps({"path": str(pathlib.Path(path).resolve()), "title": title})

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
            if isinstance(v, pd.Timedelta):
                cells.append(None if pd.isna(v) else v.total_seconds())
            elif hasattr(v, "__float__"):
                cells.append(float(v))
            else:
                cells.append(v)
        rows.append(cells)
    return rows


def _system_instructions(stream: "Eventstream", context: dict) -> str:
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
        "Available tools:",
        "- describe()                  — stream schema and event list",
        "- transition_graph_data()     — Markov transition matrix",
        "- export_html()               — interactive transition graph HTML report",
        "- step_matrix_data()          — step matrix (event frequency per step position)",
        "- export_step_matrix_html()   — interactive step matrix HTML report",
        "",
        "When reporting findings:",
        "- Wrap event names in [square brackets] — e.g. [basket], [purchase].",
        "- Always call the relevant export_*_html() tool with your analysis text.",
        "  In the analysis, [event_name] references become clickable links.",
        "- Tell the user the file path so they can open it.",
        "- Use markdown in analysis: # headings, **bold**, tables, - bullet lists.",
    ]
    return "\n".join(lines)
