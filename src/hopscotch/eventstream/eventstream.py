import json
from dataclasses import asdict, dataclass, field
from functools import cached_property

import duckdb
import pandas as pd

from hopscotch.eventstream.event_type import EventTypes
from hopscotch.eventstream.schema import EventstreamSchema
from hopscotch.tools.types import T_TransitionMatrixValues, T_Diff


def _to_datetime_auto(series: pd.Series) -> pd.Series:
    if pd.api.types.is_integer_dtype(series):
        n = len(str(abs(int(series.iloc[0]))))
        unit = "s" if n <= 10 else "ms" if n <= 13 else "us" if n <= 16 else "ns"
        return pd.to_datetime(series, unit=unit)
    return pd.to_datetime(series)


@dataclass
class Eventstream:
    _df: pd.DataFrame | str
    _schema: dict | None = field(default=None)
    prepare: bool = field(default=True)

    @cached_property
    def schema(self) -> EventstreamSchema:
        return EventstreamSchema(**(self._schema or {}))

    @property
    def df(self) -> pd.DataFrame:
        return self._df

    @df.setter
    def df(self, v: pd.DataFrame):
        self._df = v

    def __post_init__(self):
        if self.prepare:
            self._prepare()
        else:
            for col in self.schema.event_cols + self.schema.segment_cols:
                self._df[col] = self._df[col].astype("category")

    def _prepare(self):
        if isinstance(self._df, str):
            df = pd.read_csv(self._df)
        elif isinstance(self._df, pd.DataFrame):
            df = self._df.copy()
        else:
            raise ValueError(f"_df must be a DataFrame or CSV path, got {type(self._df)}")

        schema = self.schema
        event_types = EventTypes()

        df[schema.timestamp] = _to_datetime_auto(df[schema.timestamp])

        for col in schema.path_cols:
            if df[col].dtype == "float64":
                df[col] = df[col].astype("str")

        for col in schema.event_cols + schema.segment_cols:
            df[col] = df[col].astype("category")

        if schema.event_type not in df.columns:
            df[schema.event_type] = event_types.RAW_EVENT.type
        if schema.subindex not in df.columns:
            df[schema.subindex] = df[schema.event_type].map(event_types.get_order())

        df = df.sort_values(
            [schema.path_col, schema.timestamp, schema.subindex]
        ).reset_index(drop=True)

        if schema.index not in df.columns:
            df[schema.index] = df.groupby(schema.path_col).cumcount() + 1

        self._df = df

    def to_dataframe(self, exclude_start_end: bool = True) -> pd.DataFrame:
        df = self._df.copy()
        if exclude_start_end:
            exclude = [EventTypes().PATH_START.type, EventTypes().PATH_END.type]
            df = df[~df[self.schema.event_type].isin(exclude)]
        return df

    def empty(self, exclude_start_end: bool = True) -> bool:
        return self.to_dataframe(exclude_start_end=exclude_start_end).empty

    def equals(self, other: "Eventstream", exclude_start_end: bool = False, ignore_technical_columns: bool = True) -> bool:
        df1 = self.to_dataframe(exclude_start_end=exclude_start_end).reset_index(drop=True)
        df2 = other.to_dataframe(exclude_start_end=exclude_start_end).reset_index(drop=True)
        if ignore_technical_columns:
            drop = [self.schema.event_type, self.schema.index, self.schema.subindex]
            df1 = df1.drop(columns=[c for c in drop if c in df1.columns])
            df2 = df2.drop(columns=[c for c in drop if c in df2.columns])
        if set(df1.columns) != set(df2.columns):
            return False
        df2 = df2[df1.columns]
        return pd.DataFrame.equals(df1, df2)

    def get_event_counts(self, event_col: str | None = None) -> dict[str, int]:
        import duckdb
        event_col = event_col or self.schema.event_col
        df = self._df
        query = f"SELECT {event_col}, COUNT(*) AS cnt FROM df GROUP BY {event_col}"
        return duckdb.sql(query).df().set_index(event_col)["cnt"].to_dict()

    def get_all_segment_levels(self) -> dict[str, list[str]]:
        return {
            col: self._df[col].cat.categories.tolist()
            for col in self.schema.segment_cols
        }

    def filter_events(self, values: dict | None = None, func=None, sql: str | None = None) -> "Eventstream":
        from hopscotch.data_processors.filter_events import FilterEvents
        if values is None and func is None and sql is None:
            return Eventstream(self._df.copy(), asdict(self.schema), prepare=False)
        new_df, new_schema = FilterEvents(values=values, func=func, sql=sql).apply(self._df, self.schema)
        return Eventstream(new_df, asdict(new_schema), prepare=False)

    def add_clusters(self, segment_name: str, features: list, method: str = "kmeans", scaler=None, n_clusters=None, min_cluster_size=None, cluster_selection_epsilon=None, nmf_k=None, path_id_col=None, event_col=None) -> "Eventstream":
        from hopscotch.data_processors.add_clusters import AddClusters
        new_df, new_schema = AddClusters(eventstream=self, segment_name=segment_name, metrics=features, method=method, scaler=scaler, n_clusters=n_clusters, min_cluster_size=min_cluster_size, cluster_selection_epsilon=cluster_selection_epsilon, nmf_k=nmf_k, path_id_col=path_id_col, event_col=event_col).apply(self._df, self.schema)
        return Eventstream(new_df, asdict(new_schema), prepare=False)

    def url_events(self, column: str, nodes: list, strip_host: bool = True, strip_cgi: bool = True, strip_locale: bool = True, slug_enabled: bool = True, host_col=None, cgi_col=None, locale_col=None, slug_col=None) -> "Eventstream":
        from hopscotch.data_processors.url_events import UrlEvents
        new_df, new_schema = UrlEvents(column=column, nodes=nodes, strip_host=strip_host, strip_cgi=strip_cgi, strip_locale=strip_locale, slug_enabled=slug_enabled, host_col=host_col, cgi_col=cgi_col, locale_col=locale_col, slug_col=slug_col).apply(self._df, self.schema)
        return Eventstream(new_df, asdict(new_schema), prepare=False)

    def filter_paths(self, ast_condition: dict, path_id_col: str | None = None, event_col: str | None = None) -> "Eventstream":
        """
        Filter paths based on an AST condition.

        The ast_condition can include various metrics like:
        - event_count: count of specific events
        - has: presence of specific event(s)
        - matches: whether path matches a pattern
        - length, duration, time_between, active_days, etc.

        Example:
            ast_condition = {
                "op": "and",
                "args": [
                    {"op": ">", "metric": "event_count", "value": 1, "metric_args": {"event": "purchase"}},
                    {"op": "=", "metric": "matches", "value": True, "metric_args": {"pattern": "registration->.*->purchase"}},
                ]
            }
        """
        from hopscotch.data_processors.filter_paths import FilterPaths
        from hopscotch.exceptions import EmptyEventstreamError

        dp = FilterPaths(ast_condition, path_id_col, event_col)
        path_id_col = path_id_col or self.schema.path_col

        # Extract metric configs
        metric_configs = dp._get_metric_configs(ast_condition)

        # Build metrics
        metrics = self.get_metrics(metric_configs, path_id_col=path_id_col).reset_index()
        condition = dp._get_where_condition(ast_condition)
        query = f"SELECT {path_id_col} FROM metrics WHERE {condition}"
        path_ids = duckdb.sql(query).df()[path_id_col].tolist()

        if len(path_ids) == 0:
            raise EmptyEventstreamError("no paths match the filter_paths condition")

        result_stream = self.filter_events(values={"column": path_id_col, "values": path_ids})
        if result_stream.empty():
            raise EmptyEventstreamError("no events remain after filter_paths")
        return result_stream

    def get_metrics(self, metrics: list, path_id_col: str | None = None) -> pd.DataFrame:
        """
        Build metrics for each path in the eventstream.

        Args:
            metrics: List of metric configuration dicts with 'metric' and optional 'metric_args' fields
            path_id_col: Path ID column (if None, taken from schema)

        Returns:
            DataFrame with path_id as index and metrics as columns
        """
        from hopscotch.metrics.metric_builder import MetricBuilder
        builder = MetricBuilder(self)
        return builder.build_metrics(metrics, path_id_col)

    def add_events(self, new_event_name: str, source_events=None, sql=None, churn=None) -> "Eventstream":
        from hopscotch.data_processors.add_events import AddEvents
        new_df, new_schema = AddEvents(new_event_name, source_events=source_events, sql=sql, churn=churn).apply(self._df, self.schema)
        return Eventstream(new_df, asdict(new_schema), prepare=False)

    def add_segment(self, name: str, values=None, func=None, sql=None) -> "Eventstream":
        from hopscotch.data_processors.add_segment import AddSegment
        new_df, new_schema = AddSegment(name, values=values, func=func, sql=sql).apply(self._df, self.schema)
        return Eventstream(new_df, asdict(new_schema), prepare=False)

    def collapse_events(self, repetitive=None, event_groups=None, event_from_col=None, daily_states=None, session_id_col=None, session_type_col=None, agg=None, path_id_col=None, event_col=None) -> "Eventstream":
        from hopscotch.data_processors.collapse_events import CollapseEvents
        new_df, new_schema = CollapseEvents(repetitive=repetitive, event_groups=event_groups, event_from_col=event_from_col, daily_states=daily_states, session_id_col=session_id_col, session_type_col=session_type_col, agg=agg, path_id_col=path_id_col, event_col=event_col).apply(self._df, self.schema)
        return Eventstream(new_df, new_schema.__dict__, prepare=False)

    def drop_segment(self, name: str) -> "Eventstream":
        from hopscotch.data_processors.drop_segment import DropSegment
        new_df, new_schema = DropSegment(name).apply(self._df, self.schema)
        return Eventstream(new_df, asdict(new_schema), prepare=False)

    def edit_events(self, rename=None, delete=None) -> "Eventstream":
        from hopscotch.data_processors.edit_events import EditEvents
        new_df, new_schema = EditEvents(rename=rename, delete=delete).apply(self._df, self.schema)
        return Eventstream(new_df, asdict(new_schema), prepare=False)

    def rename_events(self, mapping: dict) -> "Eventstream":
        from hopscotch.data_processors.rename_events import RenameEvents
        new_df, new_schema = RenameEvents(mapping).apply(self._df, self.schema)
        return Eventstream(new_df, asdict(new_schema), prepare=False)

    def sample_paths(self, sample_size, random_state=None, path_id_col=None) -> "Eventstream":
        from hopscotch.data_processors.sample_paths import SamplePaths
        new_df, new_schema = SamplePaths(sample_size=sample_size, random_state=random_state, path_id_col=path_id_col).apply(self._df, self.schema)
        return Eventstream(new_df, asdict(new_schema), prepare=False)

    def split_sessions(self, session_col="session_id", session_index_col="session_index", separator=None, start_event=None, end_event=None, timeout=None, path_id_col=None, event_col=None) -> "Eventstream":
        from hopscotch.data_processors.split_sessions import SplitSessions
        new_df, new_schema = SplitSessions(session_col=session_col, session_index_col=session_index_col, separator=separator, start_event=start_event, end_event=end_event, timeout=timeout, path_id_col=path_id_col, event_col=event_col).apply(self._df, self.schema)
        return Eventstream(new_df, asdict(new_schema), prepare=False)

    def truncate_paths(self, left: str, right: str, path_id_col=None, event_col=None) -> "Eventstream":
        from hopscotch.data_processors.truncate_paths import TruncatePaths
        new_df, new_schema = TruncatePaths(left=left, right=right, path_id_col=path_id_col, event_col=event_col).apply(self._df, self.schema)
        return Eventstream(new_df, asdict(new_schema), prepare=False)

    def split_two(self, split, path_id_col: str | None = None):
        from hopscotch.exceptions import EmptyEventstreamError, DiffConfigError
        if len(split) == 3:
            segment_col, v1, v2 = split[0], split[1], split[2]
            if segment_col not in self.schema.segment_cols:
                raise DiffConfigError(f"'{segment_col}' is not a segment column")
            s1 = self.filter_events({"column": segment_col, "values": [v1]})
            if v2 == "<OUTER>":
                all_vals = set(self.get_all_segment_levels().get(segment_col, []))
                v2_vals = list(all_vals - {v1})
            else:
                v2_vals = [v2]
            s2 = self.filter_events({"column": segment_col, "values": v2_vals})
        elif len(split) == 2:
            ids1, ids2 = split[0], split[1]
            path_id_col = path_id_col or self.schema.path_col
            s1 = self.filter_events({"column": path_id_col, "values": list(ids1)})
            s2 = self.filter_events({"column": path_id_col, "values": list(ids2)})
        else:
            raise DiffConfigError("diff must be (seg, v1, v2) or (ids1, ids2)")
        if s1.empty():
            raise EmptyEventstreamError("first diff group is empty")
        if s2.empty():
            raise EmptyEventstreamError("second diff group is empty")
        return s1, s2

    def add_start_end_events(self, path_id_col: str | None = None) -> "Eventstream":
        from hopscotch.data_processors.add_start_end_events import AddStartEndEvents
        dp = AddStartEndEvents(path_id_col)
        new_df, new_schema = dp.apply(self._df, self.schema)
        return Eventstream(new_df, asdict(new_schema), prepare=False)

    def transition_matrix(
        self,
        values: T_TransitionMatrixValues = "proba_out",
        path_id_col: str | None = None,
        diff: T_Diff = None,
    ) -> pd.DataFrame:
        from hopscotch.tools.transition_matrix import TransitionMatrix
        return TransitionMatrix(self).fit(values, diff, path_id_col)

    def step_matrix(
        self,
        max_steps: int = 10,
        diff: T_Diff = None,
        path_id_col: str | None = None,
        path_pattern: str | None = None,
    ):
        from hopscotch.tools.step_matrix import StepMatrix
        return StepMatrix(self).fit(
            max_steps=max_steps, diff=diff,
            path_id_col=path_id_col, path_pattern=path_pattern,
        )

    def step_sankey(
        self,
        max_steps=None,
        diff=None,
        path_id_col=None,
        path_pattern=None,
        height=None,
        sidebar_open=None,
        object_name: str | None = None,
        load_from: str | None = None,
    ):
        from hopscotch.widgets.step_sankey import StepSankeyWidget, _UNSET
        return StepSankeyWidget(
            eventstream=self,
            object_name=object_name,
            load_from=load_from,
            max_steps=max_steps         if max_steps    is not None else _UNSET,
            diff=diff                   if diff         is not None else _UNSET,
            path_id_col=path_id_col     if path_id_col  is not None else _UNSET,
            path_pattern=path_pattern   if path_pattern is not None else _UNSET,
            height=height               if height       is not None else _UNSET,
            sidebar_open=sidebar_open   if sidebar_open is not None else _UNSET,
        )

    def transition_graph(
        self,
        values=None,
        diff=None,
        path_id_col=None,
        height=None,
        sidebar_open=None,
        object_name: str | None = None,
        load_from: str | None = None,
    ):
        from hopscotch.widgets.transition_graph import TransitionGraphWidget, _UNSET
        return TransitionGraphWidget(
            eventstream=self,
            object_name=object_name,
            load_from=load_from,
            values=values         if values       is not None else _UNSET,
            diff=diff             if diff         is not None else _UNSET,
            path_id_col=path_id_col if path_id_col is not None else _UNSET,
            height=height         if height       is not None else _UNSET,
            sidebar_open=sidebar_open if sidebar_open is not None else _UNSET,
        )
