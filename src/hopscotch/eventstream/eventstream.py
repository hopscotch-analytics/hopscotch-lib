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

    def filter_events(self, values: dict | None = None) -> "Eventstream":
        df = self._df.copy()
        if values:
            col = values.get("column")
            vals = values.get("values", [])
            exclude = values.get("exclude", False)
            if col and vals:
                vals_str = json.dumps(list(vals)).replace('"', "'")[1:-1]
                operator = "not in" if exclude else "in"
                query = f"""
                    select * from df
                    where {col} {operator} ({vals_str})
                    order by {self.schema.path_col}, {self.schema.index}, {self.schema.subindex}
                """
                df = duckdb.sql(query).df()
                for c in self.schema.event_cols + self.schema.segment_cols:
                    if c in df.columns:
                        df[c] = df[c].astype("category")
        return Eventstream(df, asdict(self.schema), prepare=False)

    def split_two(self, split, path_id_col: str | None = None):
        from hopscotch.exceptions import EmptyEventstreamError, DiffConfigError
        if len(split) == 3:
            segment_col, v1, v2 = split[0], split[1], split[2]
            if segment_col not in self.schema.segment_cols:
                raise DiffConfigError(f"'{segment_col}' is not a segment column")
            s1 = self.filter_events({"column": segment_col, "values": [v1]})
            s2 = self.filter_events({"column": segment_col, "values": [v2]})
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
