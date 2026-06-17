from dataclasses import dataclass
from typing import TYPE_CHECKING, Tuple

import duckdb
import pandas as pd

from hopscotch.eventstream.event_type import EventTypes
from hopscotch.exceptions import EmptyEventstreamError, InvalidParameterError
from .types import T_Diff

if TYPE_CHECKING:
    from hopscotch.eventstream.eventstream import Eventstream


@dataclass
class StepMatrix:
    eventstream: "Eventstream"

    def fit(
        self,
        max_steps: int = 10,
        diff: T_Diff = None,
        path_id_col: str | None = None,
    ) -> Tuple[pd.DataFrame, ...]:
        path_id_col = path_id_col or self.eventstream.schema.path_col

        if self.eventstream.empty():
            raise EmptyEventstreamError("Cannot calculate step matrix for empty eventstream")

        if path_id_col not in self.eventstream.schema.path_cols:
            raise InvalidParameterError("path_id_col", path_id_col, self.eventstream.schema.path_cols)

        if diff is None:
            sm = self._regular(max_steps, path_id_col)
            return (sm,)

        stream1, stream2 = self.eventstream.split_two(diff, path_id_col=path_id_col)
        sms1 = StepMatrix(stream1).fit(max_steps=max_steps, path_id_col=path_id_col)
        sms2 = StepMatrix(stream2).fit(max_steps=max_steps, path_id_col=path_id_col)
        sms1, sms2 = _align(list(sms1), list(sms2))
        diff_sms = tuple(sms2[i] - sms1[i] for i in range(len(sms1)))
        return diff_sms, tuple(sms1), tuple(sms2)

    def _regular(self, max_steps: int, path_id_col: str) -> pd.DataFrame:
        event_col = self.eventstream.schema.event_col
        index_col = self.eventstream.schema.index
        subindex_col = self.eventstream.schema.subindex
        path_start = EventTypes().PATH_START.name
        path_end = EventTypes().PATH_END.name

        df = self.eventstream.df

        query = f"""
            select step, {event_col}, count(*) as value
            from (
                select {path_id_col}, {event_col},
                    row_number() over (
                        partition by {path_id_col}
                        order by {index_col}, {subindex_col}
                    ) as step
                from df
            )
            where step <= {max_steps}
            group by step, {event_col}
            order by step, {event_col}
        """
        sm = (
            duckdb.sql(query)
            .df()
            .pivot_table(index=event_col, columns="step", values="value", observed=False)
        )

        sm = sm.reindex(columns=range(max_steps + 1)).fillna(0)
        total_paths = int(sm[1].sum())
        sm.loc[path_start, 0] = total_paths
        sm.loc[path_start, 1:] = 0
        sm.loc[path_end, :] = pd.Series(total_paths, index=sm.columns) - sm.sum()

        event_order = (
            [path_start]
            + sm.index.drop([path_start, path_end], errors="ignore").tolist()
            + [path_end]
        )
        sm = sm.loc[event_order, :]
        sm /= total_paths
        return sm


def _align(sms1, sms2):
    from functools import reduce
    path_start = EventTypes().PATH_START.name
    path_end = EventTypes().PATH_END.name
    indices = [sm.index for sm in (sms1 + sms2)]
    index = reduce(lambda a, b: a.union(b), indices)
    index = (
        [path_start]
        + index.drop([path_start, path_end], errors="ignore").tolist()
        + [path_end]
    )
    aligned1, aligned2 = [], []
    for i in range(len(sms1)):
        cols = sms1[i].columns.union(sms2[i].columns)
        aligned1.append(sms1[i].reindex(index=index, columns=cols).fillna(0))
        aligned2.append(sms2[i].reindex(index=index, columns=cols).fillna(0))
    return aligned1, aligned2
