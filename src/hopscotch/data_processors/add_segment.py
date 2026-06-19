from typing import Callable, Collection, Tuple

import duckdb
import pandas as pd

from hopscotch.data_processors.data_processor import DataProcessor
from hopscotch.eventstream.schema import EventstreamSchema
from hopscotch.exceptions import PreprocessingConfigError

PROCESSOR_NAME = "add_segment"

_ROW_IDX_COL = "__hopscotch_row_idx__"


def _inject_row_idx(sql: str) -> str:
    """
    Injects _ROW_IDX_COL into the outermost SELECT of a SQL query.

    DuckDB reorders rows when executing window functions with PARTITION BY,
    so we inject a row index column into the result to restore the original order.

    Works for both plain SELECT and CTEs (WITH ... SELECT ...).
    """
    stripped = sql.strip()
    depth = 0
    i = 0
    in_single_quote = False
    in_double_quote = False

    while i < len(stripped):
        c = stripped[i]

        if in_single_quote:
            if c == "'" and (i == 0 or stripped[i - 1] != "\\"):
                in_single_quote = False
        elif in_double_quote:
            if c == '"' and (i == 0 or stripped[i - 1] != "\\"):
                in_double_quote = False
        elif c == "'":
            in_single_quote = True
        elif c == '"':
            in_double_quote = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and stripped[i : i + 6].upper() == "SELECT":
            before_ok = i == 0 or not (stripped[i - 1].isalnum() or stripped[i - 1] == "_")
            end_pos = i + 6
            after_ok = end_pos >= len(stripped) or not (
                stripped[end_pos].isalnum() or stripped[end_pos] == "_"
            )
            if before_ok and after_ok:
                return stripped[:end_pos] + f" {_ROW_IDX_COL}," + stripped[end_pos:]

        i += 1

    raise PreprocessingConfigError(
        PROCESSOR_NAME, "Could not find SELECT statement in SQL query."
    )


class AddSegment(DataProcessor):
    name: str
    values: Collection | None
    func: Callable | None
    sql: str | None

    def __init__(
        self,
        name: str,
        values: Collection | None = None,
        func: Callable | None = None,
        sql: str | None = None,
    ) -> None:
        values_arg_name = f"{values=}".split("=")[0]
        func_arg_name = f"{func=}".split("=")[0]
        sql_arg_name = f"{sql=}".split("=")[0]
        arg_is_not_none = [func is not None, values is not None, sql is not None]

        if sum(arg_is_not_none) != 1:
            raise PreprocessingConfigError(
                PROCESSOR_NAME,
                f"One and only one of the arguments must be defined: {values_arg_name}, {func_arg_name}, {sql_arg_name}."
            )

        self.name = name
        self.values = values
        self.func = func
        self.sql = sql
        super().__init__()

    def apply(
        self, df: pd.DataFrame, schema: EventstreamSchema
    ) -> Tuple[pd.DataFrame, EventstreamSchema]:

        if self.name in df.columns:
            if self.name in schema.segment_cols:
                raise PreprocessingConfigError(PROCESSOR_NAME, f"Segment '{self.name}' already exists.")
            else:
                raise PreprocessingConfigError(
                    PROCESSOR_NAME,
                    f"Name '{self.name}' is already reserved in the eventstream."
                )

        values = None

        if self.values is not None:
            if not isinstance(self.values, Collection):
                raise PreprocessingConfigError(PROCESSOR_NAME, "Segment values must be a collection.")

            cases = "CASE"
            for item in self.values[:-1]:
                column, op, value, segment_value = item
                if isinstance(value, str) and op.lower() != "in":
                    value = f"'{value}'"
                cases += f"\nWHEN {column} {op} {value} THEN '{segment_value}'"
            else_segment_value = self.values[-1][0]
            cases += f"\nELSE '{else_segment_value}'"
            cases += f"\nEND AS {self.name}"

            sql = f"SELECT {cases} FROM df"
            result = duckdb.sql(sql).df()
            values = result[result.columns[0]].tolist()

        elif self.sql is not None:
            if not isinstance(self.sql, str):
                raise PreprocessingConfigError(PROCESSOR_NAME, "SQL query must be a string.")

            # Copy df and add a row index so we can restore original order after
            # DuckDB reorders rows during window function (PARTITION BY) execution.
            eventstream = df.copy()
            eventstream[_ROW_IDX_COL] = range(len(df))

            tracking_sql = _inject_row_idx(self.sql)
            result = duckdb.sql(tracking_sql).df()

            if len(result.columns) != 2:
                raise PreprocessingConfigError(PROCESSOR_NAME, "SQL script must return a single column.")

            result = result.sort_values(_ROW_IDX_COL).reset_index(drop=True)
            values = result.iloc[:, 1].tolist()

        elif self.func is not None:
            if not isinstance(self.func, Callable):
                raise PreprocessingConfigError(PROCESSOR_NAME, "Function must be callable.")
            result = self.func(df)
            if not isinstance(result, Collection):
                raise PreprocessingConfigError(PROCESSOR_NAME, "Function must return a collection.")
            values = list(result)

        new_df = df.copy()
        new_df[self.name] = values
        new_df[self.name] = new_df[self.name].astype("category")
        new_schema = schema.copy()
        new_schema.segment_cols.append(self.name)

        return new_df, new_schema
