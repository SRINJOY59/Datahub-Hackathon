"""DuckDB column profiler + deterministic anomaly classifier.

Profiles a column split recent-vs-historical (by the table's timestamp column, if
any) and classifies the change. This is what grounds RCA in real numbers instead
of LLM guesses.
"""
from __future__ import annotations

import duckdb

from agent.contracts import ChangeType, ColumnProfile
from agent.tools.warehouse.duck import connect
from ml.config import DUCKDB_PATH

_NUMERIC = {"DOUBLE", "FLOAT", "REAL", "DECIMAL", "BIGINT", "INTEGER",
            "HUGEINT", "SMALLINT", "TINYINT", "UBIGINT", "UINTEGER"}


class ColumnProfiler:
    def __init__(self, duckdb_path: str | None = None) -> None:
        self.path = str(duckdb_path or DUCKDB_PATH)

    def _cols(self, con, table: str) -> list[tuple[str, str]]:
        return con.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_name = ?", [table]
        ).fetchall()

    @staticmethod
    def _timestamp_col(cols: list[tuple[str, str]]) -> str | None:
        for name, dt in cols:
            if "TIMESTAMP" in dt.upper() or "DATE" in dt.upper():
                return name
        return None

    def numeric_columns(self, table: str) -> list[str]:
        con = connect(self.path, read_only=True)
        try:
            return [c for c, dt in self._cols(con, table)
                    if dt.upper().split("(")[0] in _NUMERIC]
        finally:
            con.close()

    def profile_column(self, table: str, column: str) -> ColumnProfile:
        con = connect(self.path, read_only=True)
        try:
            cols = self._cols(con, table)
            if column not in [c for c, _ in cols]:
                return ColumnProfile(dataset_urn="", table=table, column=column,
                                     exists=False, note="column missing")
            tcol = self._timestamp_col(cols)
            total, nulls, mn, mx, avg, dist = con.execute(
                f'select count(*), count(*) filter (where "{column}" is null), '
                f'min("{column}"), max("{column}"), avg("{column}"), '
                f'count(distinct "{column}") from "{table}"'
            ).fetchone()
            null_rate = nulls / total if total else 0.0

            recent_null, recent_mean = null_rate, avg
            if tcol:
                cutoff = con.execute(
                    f'select quantile_cont(epoch("{tcol}"), 0.8) from "{table}"'
                ).fetchone()[0]
                r = con.execute(
                    f'select count(*), count(*) filter (where "{column}" is null), '
                    f'avg("{column}") from "{table}" where epoch("{tcol}") >= ?',
                    [cutoff],
                ).fetchone()
                recent_null = (r[1] / r[0]) if r[0] else 0.0
                recent_mean = r[2]

            return ColumnProfile(
                dataset_urn="", table=table, column=column,
                null_rate=null_rate, recent_null_rate=recent_null,
                mean=avg, recent_mean=recent_mean,
                minimum=mn, maximum=mx, distinct=dist,
            )
        finally:
            con.close()


def feature_target_correlations(table: str, features: list[str], target: str,
                                duckdb_path: str | None = None) -> dict[str, float]:
    """How strongly each feature tracks the label.

    A feature that predicts the target almost perfectly has usually been
    contaminated by it — the model is reading the answer rather than inferring
    it. This is the evidence behind a label-leakage incident, and the reason a
    suspiciously *good* model is an incident at all.
    """
    con = connect(str(duckdb_path or DUCKDB_PATH), read_only=True)
    try:
        present = {c for c, _ in con.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_name = ?", [table]
        ).fetchall()}
        usable = [f for f in features if f in present]
        if target not in present or not usable:
            return {}

        selects = ", ".join(f'corr("{f}", "{target}")' for f in usable)
        row = con.execute(f'select {selects} from "{table}"').fetchone()
    except duckdb.Error:
        return {}
    finally:
        con.close()

    return {f: float(v) for f, v in zip(usable, row or []) if v is not None}


# A leaking feature is not merely well-correlated with the label — plenty of
# honest features are — it is correlated *far* beyond everything else, because it
# is carrying the answer rather than evidence for it. Judging that in absolute
# terms alone would either miss real leaks or flag genuinely predictive features,
# so the test is a floor plus a dominance ratio over the runner-up.
LEAK_FLOOR = 0.4
LEAK_DOMINANCE = 3.0


def identify_leaks(correlations: dict[str, float]) -> dict[str, float]:
    """Which features, if any, look like they are carrying the label."""
    if len(correlations) < 2:
        return {}
    ranked = sorted(correlations.items(), key=lambda kv: -abs(kv[1]))
    top_name, top_value = ranked[0]
    runner_up = abs(ranked[1][1]) or 1e-9

    if abs(top_value) < LEAK_FLOOR:
        return {}
    if abs(top_value) / runner_up < LEAK_DOMINANCE:
        return {}
    return {top_name: top_value}


def classify(p: ColumnProfile) -> tuple[ChangeType, str]:
    """Deterministically classify a column's anomaly from its profile."""
    if not p.exists:
        return ChangeType.SCHEMA_CHANGE, f"{p.table}.{p.column} is missing"
    # A column that is present but entirely empty is a rename in disguise: the
    # upstream stopped writing to it and everything reading it now silently gets
    # nothing. It looks nothing like a null *spike*, because there is no healthy
    # history to spike away from — it was never populated in this shape.
    if p.null_rate >= 0.99:
        return (ChangeType.SCHEMA_CHANGE,
                f"{p.table}.{p.column} exists but is {p.null_rate:.0%} null — "
                f"upstream has stopped populating it")
    if p.recent_null_rate - p.null_rate > 0.2 and p.recent_null_rate > 0.3:
        return (ChangeType.NULL_SPIKE,
                f"recent null rate {p.recent_null_rate:.0%} vs overall {p.null_rate:.0%}")
    if p.mean and p.recent_mean and p.mean > 0:
        ratio = p.recent_mean / p.mean
        if ratio > 3 or ratio < 0.33:
            return (ChangeType.SCALE_SHIFT,
                    f"recent mean {p.recent_mean:.2f} vs overall {p.mean:.2f} "
                    f"({ratio:.1f}x)")
        if ratio > 1.5 or ratio < 0.67:
            return (ChangeType.DISTRIBUTION_DRIFT,
                    f"recent mean {p.recent_mean:.2f} vs overall {p.mean:.2f} "
                    f"({ratio:.1f}x)")
    return ChangeType.UNKNOWN, ""
