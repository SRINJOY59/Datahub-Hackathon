"""Actuator: isolate the bad rows instead of discarding the good ones.

Where pinning throws away everything since the last snapshot, quarantine keeps
recent legitimate data and removes only what is actually wrong — the better
mitigation when a feed is mostly healthy.

What counts as "wrong" is derived from the last known-good snapshot rather than
from any knowledge of how the data broke: a row whose value falls outside the
range ever observed while the pipeline was healthy is a row the pipeline was
never built to handle. Offending rows are moved to a `sentinel_quarantine` table
named for the incident, so they can be inspected rather than simply lost.
"""
from __future__ import annotations

from agent.contracts import ActionRecord, ActionType, ChangeType
from agent.registry import actuator
from agent.tools.actuators.base import LAST_GOOD, WarehouseActuator
from agent.tools.warehouse.duck import connect
from ml.config import DUCKDB_PATH

QUARANTINE_SCHEMA = "sentinel_quarantine"


@actuator
class QuarantineActuator(WarehouseActuator):
    name = "quarantine"
    action_type = ActionType.QUARANTINE

    def _mutate(self, table: str, action: ActionRecord) -> str:
        column = action.params.get("column")
        if not column:
            raise ValueError("quarantine needs the offending column")

        predicate = self._predicate(table, column, action.params.get("change_type"))
        holding = f"{table}__{(action.incident_id or 'manual').replace('-', '_')}"

        con = connect(str(DUCKDB_PATH))
        try:
            moved = con.execute(
                f'select count(*) from main."{table}" where {predicate}'
            ).fetchone()[0]
            if not moved:
                raise RuntimeError(
                    f"no rows in {table} match the quarantine predicate "
                    f"({predicate}) — nothing to isolate"
                )
            con.execute(f"create schema if not exists {QUARANTINE_SCHEMA}")
            con.execute(
                f'create or replace table {QUARANTINE_SCHEMA}."{holding}" as '
                f'select * from main."{table}" where {predicate}'
            )
            con.execute(f'delete from main."{table}" where {predicate}')
        finally:
            con.close()

        return (f"quarantined {moved} row(s) from {table} where {predicate} "
                f"-> {QUARANTINE_SCHEMA}.{holding}")

    # ------------------------------------------------------------------ #
    def _predicate(self, table: str, column: str, change_type: str | None) -> str:
        """What to isolate, expressed in terms of healthy history."""
        if change_type == ChangeType.NULL_SPIKE.value:
            return f'"{column}" is null'

        bounds = self._healthy_bounds(table, column)
        if bounds is None:
            raise RuntimeError(
                f"no '{LAST_GOOD}' snapshot of {table} to derive a safe range "
                f"for {column} — cannot decide which rows are bad"
            )
        low, high = bounds
        return (f'("{column}" is null or "{column}" < {low} or "{column}" > {high})')

    def _healthy_bounds(self, table: str, column: str) -> tuple[float, float] | None:
        if not self.snapshots.exists(table, LAST_GOOD):
            return None
        snap = f'{table}__{LAST_GOOD}'
        con = connect(str(DUCKDB_PATH), read_only=True)
        try:
            row = con.execute(
                f'select min("{column}"), max("{column}") '
                f'from sentinel_snap."{snap}"'
            ).fetchone()
        except Exception:
            return None
        finally:
            con.close()
        if not row or row[0] is None or row[1] is None:
            return None
        return float(row[0]), float(row[1])
