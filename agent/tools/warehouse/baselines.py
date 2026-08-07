"""What the pipeline looks like when it is healthy.

Some failures leave every dbt assertion green: a feed that stops delivering, or a
batch that arrives at a tenth of its usual size, breaks nothing a null-check or
range-check would notice. The only way to see them is to know what normal looked
like — so when a reset finishes green, we record the shape of the warehouse.

Captured per table: row count, newest timestamp, and the timestamp column used.
Written to .sentinel/baselines.json rather than into DuckDB so that a rebuild of
the warehouse can't quietly erase the very reference we compare against.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from agent.tools.warehouse.duck import connect
from ml.config import DUCKDB_PATH

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PATH = REPO_ROOT / ".sentinel" / "baselines.json"


@dataclass
class TableBaseline:
    table: str
    row_count: int
    max_timestamp: str | None = None   # ISO8601
    timestamp_column: str | None = None


class BaselineStore:
    def __init__(self, path: Path | str = DEFAULT_PATH,
                 duckdb_path: str | Path | None = None) -> None:
        self.path = Path(path)
        self.duckdb_path = str(duckdb_path or DUCKDB_PATH)

    # ------------------------------------------------------------------ #
    def capture(self) -> dict[str, TableBaseline]:
        baselines = {b.table: b for b in self._measure_all()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "tables": {k: asdict(v) for k, v in baselines.items()},
        }, indent=2), encoding="utf-8")
        return baselines

    def load(self) -> dict[str, TableBaseline]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: TableBaseline(**v) for k, v in (data.get("tables") or {}).items()}

    def captured_at(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("captured_at")
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------------ #
    def measure(self, table: str) -> TableBaseline | None:
        con = connect(self.duckdb_path, read_only=True)
        try:
            return self._measure(con, table)
        except duckdb.Error:
            return None
        finally:
            con.close()

    def current(self) -> dict[str, TableBaseline]:
        return {b.table: b for b in self._measure_all()}

    # ------------------------------------------------------------------ #
    def _measure_all(self) -> list[TableBaseline]:
        con = connect(self.duckdb_path, read_only=True)
        out: list[TableBaseline] = []
        try:
            rows = con.execute(
                "select table_name from information_schema.tables "
                "where table_schema = 'main' order by table_name"
            ).fetchall()
            for (table,) in rows:
                measured = self._measure(con, table)
                if measured:
                    out.append(measured)
        except duckdb.Error:
            return out
        finally:
            con.close()
        return out

    @staticmethod
    def _measure(con, table: str) -> TableBaseline | None:
        try:
            cols = con.execute(
                "select column_name, data_type from information_schema.columns "
                "where table_name = ? and table_schema = 'main'", [table],
            ).fetchall()
            tcol = next(
                (c for c, dt in cols
                 if "TIMESTAMP" in dt.upper() or "DATE" in dt.upper()),
                None,
            )
            count = con.execute(f'select count(*) from main."{table}"').fetchone()[0]
            newest = None
            if tcol:
                row = con.execute(
                    f'select max("{tcol}") from main."{table}"'
                ).fetchone()
                if row and row[0] is not None:
                    newest = str(row[0])
            return TableBaseline(table=table, row_count=int(count),
                                 max_timestamp=newest, timestamp_column=tcol)
        except duckdb.Error:
            return None
