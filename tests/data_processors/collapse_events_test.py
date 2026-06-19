import pandas as pd
import pytest

from hopscotch.eventstream.eventstream import Eventstream
from hopscotch.eventstream.event_type import EventTypes
from hopscotch.exceptions import PreprocessingConfigError


SCHEMA = {"path_cols": ["user_id"], "event_cols": ["event"], "timestamp": "timestamp"}

COLLAPSED = EventTypes().COLLAPSED_EVENT.type


def make_stream(rows):
    df = pd.DataFrame(rows, columns=["user_id", "event", "timestamp"])
    return Eventstream(df, SCHEMA)


def events(stream):
    return list(stream.df["event"].astype(str))


def event_types(stream):
    return list(stream.df[stream.schema.event_type].astype(str))


# ---------------------------------------------------------------------------
# Repetitive mode
# ---------------------------------------------------------------------------

class TestCollapseEventsRepetitive:

    def test_repetitive_collapse(self):
        df = pd.DataFrame([
            ["u1", "A", "2023-01-01 00:00:00"],
            ["u1", "A", "2023-01-01 00:01:00"],
            ["u1", "B", "2023-01-01 00:02:00"],
            ["u1", "B", "2023-01-01 00:03:00"],
            ["u1", "B", "2023-01-01 00:04:00"],
            ["u1", "C", "2023-01-01 00:05:00"],
        ], columns=["user_id", "event", "timestamp"])
        stream = Eventstream(df)
        res = stream.collapse_events(repetitive=True)

        expected = Eventstream(pd.DataFrame([
            ["u1", "A", "2023-01-01 00:00:00"],
            ["u1", "B", "2023-01-01 00:02:00"],
            ["u1", "C", "2023-01-01 00:05:00"],
        ], columns=["user_id", "event", "timestamp"]))
        assert res.equals(expected)

    def test_repetitive_with_event_list(self):
        """Only specified events are collapsed; others remain as-is."""
        df = pd.DataFrame([
            ["u1", "A", "2023-01-01 00:00:00"],
            ["u1", "A", "2023-01-01 00:01:00"],
            ["u1", "A", "2023-01-01 00:02:00"],
            ["u1", "B", "2023-01-01 00:03:00"],
            ["u1", "B", "2023-01-01 00:04:00"],
            ["u1", "C", "2023-01-01 00:05:00"],
            ["u1", "C", "2023-01-01 00:06:00"],
        ], columns=["user_id", "event", "timestamp"])
        stream = Eventstream(df)
        res = stream.collapse_events(repetitive=["A", "B"])

        expected = Eventstream(pd.DataFrame([
            ["u1", "A", "2023-01-01 00:00:00"],
            ["u1", "B", "2023-01-01 00:03:00"],
            ["u1", "C", "2023-01-01 00:05:00"],
            ["u1", "C", "2023-01-01 00:06:00"],
        ], columns=["user_id", "event", "timestamp"]))
        assert res.equals(expected)

    def test_repetitive_with_single_event_in_list(self):
        """Repetitive list with one event collapses only that event."""
        df = pd.DataFrame([
            ["u1", "A", "2023-01-01 00:00:00"],
            ["u1", "A", "2023-01-01 00:01:00"],
            ["u1", "B", "2023-01-01 00:02:00"],
            ["u1", "B", "2023-01-01 00:03:00"],
            ["u1", "C", "2023-01-01 00:04:00"],
        ], columns=["user_id", "event", "timestamp"])
        stream = Eventstream(df)
        res = stream.collapse_events(repetitive=["A"])

        expected = Eventstream(pd.DataFrame([
            ["u1", "A", "2023-01-01 00:00:00"],
            ["u1", "B", "2023-01-01 00:02:00"],
            ["u1", "B", "2023-01-01 00:03:00"],
            ["u1", "C", "2023-01-01 00:04:00"],
        ], columns=["user_id", "event", "timestamp"]))
        assert res.equals(expected)

    def test_path_id_override_and_agg(self):
        df = pd.DataFrame([
            ["user_1", "sess_1", "A", "2023-01-01 00:00:00", 1],
            ["user_1", "sess_1", "A", "2023-01-01 00:01:00", 3],
            ["user_1", "sess_2", "B", "2023-01-01 00:02:00", 5],
            ["user_1", "sess_2", "B", "2023-01-01 00:03:00", 2],
        ], columns=["user_id", "session_id", "event", "timestamp", "score"])
        schema = {"path_cols": ["user_id", "session_id"], "custom_cols": ["score"]}
        stream = Eventstream(df, schema)
        res = stream.collapse_events(repetitive=True, agg={"score": "max"}, path_id_col="session_id")

        expected = Eventstream(pd.DataFrame([
            ["user_1", "sess_1", "A", "2023-01-01 00:00:00", 3],
            ["user_1", "sess_2", "B", "2023-01-01 00:02:00", 5],
        ], columns=["user_id", "session_id", "event", "timestamp", "score"]), schema)
        assert res.equals(expected)


# ---------------------------------------------------------------------------
# Event groups — all classes below use the event_groups parameter
# which was NOT ported to the library (it depends on FilterPaths).
# ---------------------------------------------------------------------------

# Not ported
# class TestCollapseEventsGroupsEvents: ...
# class TestCollapseEventsGroupsSeparator: ...
# class TestCollapseEventsGroupsStartEnd: ...
# class TestCollapseEventsGroupsTimeout: ...
# class TestCollapseEventsGroupsCases: ...
# class TestCollapseEventsMultipleGroups: ...
# class TestCollapseEventsAgg (event_groups variant): ...


# ---------------------------------------------------------------------------
# event_from_col mode
# ---------------------------------------------------------------------------

class TestCollapseEventsFromCol:

    def test_basic_col_collapse(self):
        """Consecutive runs of equal column value are collapsed into one event named after that value."""
        df = pd.DataFrame([
            ["user_1", "A", "session_type_1", "2020-01-01 00:00:00"],
            ["user_1", "B", "session_type_1", "2020-01-01 00:01:00"],
            ["user_1", "C", "session_type_2", "2020-01-01 00:02:00"],
            ["user_1", "D", "session_type_2", "2020-01-01 00:03:00"],
        ], columns=["user_id", "event", "session_type", "timestamp"])
        schema = {**SCHEMA, "custom_cols": ["session_type"]}
        stream = Eventstream(df, schema)

        res = stream.collapse_events(event_from_col="session_type")

        assert events(res) == ["session_type_1", "session_type_2"]

    def test_col_collapse_multiple_users(self):
        """Column-based collapse is independent per user."""
        df = pd.DataFrame([
            ["user_1", "A", "x", "2020-01-01 00:00:00"],
            ["user_1", "B", "x", "2020-01-01 00:01:00"],
            ["user_1", "C", "y", "2020-01-01 00:02:00"],
            ["user_2", "A", "x", "2020-01-01 00:00:00"],
            ["user_2", "B", "x", "2020-01-01 00:01:00"],
        ], columns=["user_id", "event", "col", "timestamp"])
        schema = {**SCHEMA, "custom_cols": ["col"]}
        stream = Eventstream(df, schema)

        res = stream.collapse_events(event_from_col="col")
        df_res = res.df

        u1 = list(df_res[df_res["user_id"] == "user_1"]["event"].astype(str))
        u2 = list(df_res[df_res["user_id"] == "user_2"]["event"].astype(str))
        assert u1 == ["x", "y"]
        assert u2 == ["x"]


# ---------------------------------------------------------------------------
# Daily states mode
# ---------------------------------------------------------------------------

class TestCollapseEventsDailyStates:

    def test_daily_states_first_row_is_new(self):
        df = pd.DataFrame([
            ["u1", "login", "2023-01-01 10:00:00"],
            ["u1", "purchase", "2023-01-02 10:00:00"],
        ], columns=["user_id", "event", "timestamp"])
        stream = Eventstream(df)

        # active_events not specified → all days are considered active
        res = stream.collapse_events(daily_states={"max_dormant_days": 30})
        states = res.df["event"].tolist()

        assert states[0] == "new"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestCollapseEventsValidation:

    def test_raises_no_mode(self):
        stream = make_stream([["user_1", "A", "2020-01-01"]])
        with pytest.raises(PreprocessingConfigError):
            stream.collapse_events()

    def test_raises_multiple_modes(self):
        stream = make_stream([["user_1", "A", "2020-01-01"]])
        with pytest.raises(PreprocessingConfigError):
            stream.collapse_events(repetitive=True, event_groups=[{"events": ["A"], "default": "s"}])

    def test_raises_event_from_col_not_found(self):
        stream = make_stream([["user_1", "A", "2020-01-01"]])
        with pytest.raises(PreprocessingConfigError):
            stream.collapse_events(event_from_col="nonexistent_col")

    def test_raises_event_from_col_same_as_event_col(self):
        stream = make_stream([["user_1", "A", "2020-01-01"]])
        with pytest.raises(PreprocessingConfigError):
            stream.collapse_events(event_from_col="event")

    def test_raises_session_id_col_without_session_type_col(self):
        stream = make_stream([["user_1", "A", "2020-01-01"]])
        with pytest.raises(PreprocessingConfigError):
            stream.collapse_events(session_id_col="session_id")

    def test_raises_session_id_col_not_found(self):
        stream = make_stream([["user_1", "A", "2020-01-01"]])
        with pytest.raises(PreprocessingConfigError):
            stream.collapse_events(session_id_col="nonexistent", session_type_col="also_nonexistent")

    def test_raises_session_type_col_not_found(self):
        df = pd.DataFrame([
            ["user_1", "A", 1, "2020-01-01"],
        ], columns=["user_id", "event", "session_id", "timestamp"])
        schema = {**SCHEMA, "custom_cols": ["session_id"]}
        stream = Eventstream(df, schema)
        with pytest.raises(PreprocessingConfigError):
            stream.collapse_events(session_id_col="session_id", session_type_col="nonexistent")


# ---------------------------------------------------------------------------
# Session type mode
# ---------------------------------------------------------------------------

class TestCollapseEventsBySessionType:

    def _make_stream(self, rows):
        df = pd.DataFrame(rows, columns=["user_id", "event", "session_id", "session_type", "timestamp"])
        schema = {**SCHEMA, "custom_cols": ["session_id", "session_type"]}
        return Eventstream(df, schema)

    def test_basic_collapse(self):
        """Each session collapses into one row with session_type as the event name."""
        stream = self._make_stream([
            ["user_1", "A", 1, "browse",   "2020-01-01 00:00:00"],
            ["user_1", "B", 1, "browse",   "2020-01-01 00:01:00"],
            ["user_1", "C", 2, "purchase", "2020-01-01 00:02:00"],
            ["user_1", "D", 2, "purchase", "2020-01-01 00:03:00"],
        ])
        res = stream.collapse_events(session_id_col="session_id", session_type_col="session_type")

        assert events(res) == ["browse", "purchase"]

    def test_event_type_is_collapsed(self):
        """Collapsed rows get the collapsed event_type."""
        stream = self._make_stream([
            ["user_1", "A", 1, "browse", "2020-01-01 00:00:00"],
            ["user_1", "B", 1, "browse", "2020-01-01 00:01:00"],
        ])
        res = stream.collapse_events(session_id_col="session_id", session_type_col="session_type")

        assert all(res.df[res.schema.event_type] == COLLAPSED)

    def test_earliest_timestamp_kept(self):
        """The collapsed row uses the earliest timestamp within the session."""
        stream = self._make_stream([
            ["user_1", "A", 1, "browse", "2020-01-01 00:05:00"],
            ["user_1", "B", 1, "browse", "2020-01-01 00:10:00"],
            ["user_1", "C", 1, "browse", "2020-01-01 00:15:00"],
        ])
        res = stream.collapse_events(session_id_col="session_id", session_type_col="session_type")

        ts = pd.to_datetime(res.df["timestamp"].iloc[0])
        assert ts == pd.Timestamp("2020-01-01 00:05:00")

    def test_multiple_users(self):
        """Sessions are collapsed independently per user."""
        stream = self._make_stream([
            ["user_1", "A", 1, "browse",   "2020-01-01 00:00:00"],
            ["user_1", "B", 2, "purchase", "2020-01-01 00:01:00"],
            ["user_2", "A", 3, "browse",   "2020-01-01 00:00:00"],
            ["user_2", "B", 3, "browse",   "2020-01-01 00:01:00"],
        ])
        res = stream.collapse_events(session_id_col="session_id", session_type_col="session_type")
        df = res.df

        u1 = list(df[df["user_id"] == "user_1"]["event"].astype(str))
        u2 = list(df[df["user_id"] == "user_2"]["event"].astype(str))
        assert sorted(u1) == ["browse", "purchase"]
        assert u2 == ["browse"]

    def test_single_event_per_session(self):
        """Sessions with a single event also collapse correctly."""
        stream = self._make_stream([
            ["user_1", "A", 1, "browse",   "2020-01-01 00:00:00"],
            ["user_1", "B", 2, "purchase", "2020-01-01 00:01:00"],
        ])
        res = stream.collapse_events(session_id_col="session_id", session_type_col="session_type")

        assert sorted(events(res)) == ["browse", "purchase"]

    def test_agg_max(self):
        """Custom agg is applied to extra columns."""
        df = pd.DataFrame([
            ["user_1", "A", 1, "browse", "2020-01-01 00:00:00", 10],
            ["user_1", "B", 1, "browse", "2020-01-01 00:01:00", 30],
            ["user_1", "C", 2, "purchase", "2020-01-01 00:02:00", 5],
        ], columns=["user_id", "event", "session_id", "session_type", "timestamp", "score"])
        schema = {**SCHEMA, "custom_cols": ["session_id", "session_type", "score"]}
        stream = Eventstream(df, schema)

        res = stream.collapse_events(
            session_id_col="session_id",
            session_type_col="session_type",
            agg={"score": "max"},
        )
        df_res = res.df
        browse_row = df_res[df_res["event"] == "browse"]
        assert int(browse_row["score"].iloc[0]) == 30

    def test_agg_first_is_default(self):
        """Without explicit agg, 'first' (earliest timestamp) is the default."""
        df = pd.DataFrame([
            ["user_1", "A", 1, "browse", "2020-01-01 00:00:00", 10],
            ["user_1", "B", 1, "browse", "2020-01-01 00:01:00", 20],
        ], columns=["user_id", "event", "session_id", "session_type", "timestamp", "score"])
        schema = {**SCHEMA, "custom_cols": ["session_id", "session_type", "score"]}
        stream = Eventstream(df, schema)

        res = stream.collapse_events(session_id_col="session_id", session_type_col="session_type")
        df_res = res.df
        assert int(df_res["score"].iloc[0]) == 10
