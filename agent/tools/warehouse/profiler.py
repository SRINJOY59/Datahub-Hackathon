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


def classify(p: ColumnProfile) -> tuple[ChangeType, str]:
    """Deterministically classify a column's anomaly from its profile."""
    if not p.exists:
        return ChangeType.SCHEMA_CHANGE, f"{p.table}.{p.column} is missing"
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
