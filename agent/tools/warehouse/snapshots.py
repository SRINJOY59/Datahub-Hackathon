"""Point-in-time copies of warehouse tables — the substrate of the Time Machine.

A mitigation is only safe if it can be undone exactly, so every actuator that
touches data takes a snapshot of what it is about to change *before* changing it.
That snapshot becomes the action's inverse.

Two labels matter:
  last_good   captured by PipelineReset when all assertions pass; what a rollback
              restores *to*
  pre_<id>    captured by an actuator just before it acts; what an undo restores
              *to*, so a rollback returns to the incident state rather than
              silently also discarding whatever else changed meanwhile

Views are skipped deliberately: they have no independent state, and replacing one
with a table would break the next dbt run. Restoring the base tables and letting
dbt rebuild is both simpler and closer to how a real recovery works.
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb

from agent.tools.warehouse.duck import connect
from ml.config import DUCKDB_PATH

SNAP_SCHEMA = "sentinel_snap"
_SAFE = re.compile(r"[^A-Za-z0-9_]")


def _slug(text: str) -> str:
    """Identifiers are interpolated into DDL, so anything that isn't a plain
    identifier character is stripped rather than quoted."""
    return _SAFE.sub("_", text or "").strip("_") or "unnamed"


class SnapshotStore:
    def __init__(self, duckdb_path: str | Path | None = None) -> None:
        self.path = str(duckdb_path or DUCKDB_PATH)

    # ------------------------------------------------------------------ #
    def _connect(self, read_only: bool = False):
        return connect(self.path, read_only=read_only)

    @staticmethod
    def _snap_name(table: str, label: str) -> str:
        return f"{_slug(table)}__{_slug(label)}"

    def base_tables(self) -> list[str]:
        """Real tables in `main` — views and our own snapshot schema excluded."""
        con = self._connect(read_only=True)
        try:
            rows = con.execute(
                "select table_name from information_schema.tables "
                "where table_schema = 'main' and table_type = 'BASE TABLE' "
                "order by table_name"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            con.close()

    # ------------------------------------------------------------------ #
    def capture(self, table: str, label: str) -> bool:
        """Copy `table` as it is right now. Overwrites an existing snapshot with
        the same label — re-capturing `last_good` after a green run is intended."""
        name = self._snap_name(table, label)
        con = self._connect()
        try:
            con.execute(f"create schema if not exists {SNAP_SCHEMA}")
            con.execute(
                f'create or replace table {SNAP_SCHEMA}."{name}" as '
                f'select * from main."{_slug(table)}"'
            )
            return True
        except duckdb.Error:
            return False
        finally:
            con.close()

    def capture_all(self, label: str, tables: list[str] | None = None) -> list[str]:
        targets = tables if tables is not None else self.base_tables()
        return [t for t in targets if self.capture(t, label)]

    def restore(self, table: str, label: str) -> bool:
        """Replace the live table's contents with the snapshot's.

        The rows are swapped rather than the table dropped and recreated, so
        anything holding a reference to the table keeps working.
        """
        if not self.exists(table, label):
            return False
        name = self._snap_name(table, label)
        con = self._connect()
        try:
            con.execute("begin transaction")
            con.execute(f'delete from main."{_slug(table)}"')
            con.execute(
                f'insert into main."{_slug(table)}" '
                f'select * from {SNAP_SCHEMA}."{name}"'
            )
            con.execute("commit")
            return True
        except duckdb.Error:
            try:
                con.execute("rollback")
            except duckdb.Error:
                pass
            return False
        finally:
            con.close()

    def restore_all(self, label: str, tables: list[str] | None = None) -> list[str]:
        targets = tables if tables is not None else self.labelled_tables(label)
        return [t for t in targets if self.restore(t, label)]

    # ------------------------------------------------------------------ #
    def exists(self, table: str, label: str) -> bool:
        name = self._snap_name(table, label)
        con = self._connect(read_only=True)
        try:
            row = con.execute(
                "select count(*) from information_schema.tables "
                "where table_schema = ? and table_name = ?",
                [SNAP_SCHEMA, name],
            ).fetchone()
            return bool(row and row[0])
        except duckdb.Error:
            return False
        finally:
            con.close()

    def labelled_tables(self, label: str) -> list[str]:
        """Which live tables have a snapshot under this label."""
        suffix = f"__{_slug(label)}"
        con = self._connect(read_only=True)
        try:
            rows = con.execute(
                "select table_name from information_schema.tables "
                "where table_schema = ?", [SNAP_SCHEMA],
            ).fetchall()
        except duckdb.Error:
            return []
        finally:
            con.close()
        return [r[0][: -len(suffix)] for r in rows if r[0].endswith(suffix)]

    def row_count(self, table: str, label: str | None = None) -> int:
        """Rows in the live table, or in one of its snapshots."""
        con = self._connect(read_only=True)
        try:
            if label is None:
                q = f'select count(*) from main."{_slug(table)}"'
            else:
                q = f'select count(*) from {SNAP_SCHEMA}."{self._snap_name(table, label)}"'
            row = con.execute(q).fetchone()
            return int(row[0]) if row else 0
        except duckdb.Error:
            return 0
        finally:
            con.close()

    def drop(self, table: str, label: str) -> bool:
        con = self._connect()
        try:
            con.execute(
                f'drop table if exists {SNAP_SCHEMA}."{self._snap_name(table, label)}"'
            )
            return True
        except duckdb.Error:
            return False
        finally:
            con.close()

    def drop_label(self, label: str) -> int:
        return sum(1 for t in self.labelled_tables(label) if self.drop(t, label))

    def fingerprint(self, table: str) -> str:
        """A cheap content hash, used to prove an undo really restored state."""
        con = self._connect(read_only=True)
        try:
            row = con.execute(
                f'select count(*), coalesce(sum(hash(t::varchar)), 0) '
                f'from main."{_slug(table)}" t'
            ).fetchone()
            return f"{row[0]}:{row[1]}" if row else "0:0"
        except duckdb.Error:
            return "unavailable"
        finally:
            con.close()
