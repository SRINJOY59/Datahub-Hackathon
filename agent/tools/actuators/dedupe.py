"""Actuator: drop the duplicate rows a re-delivered batch left behind.

A repair rather than a rollback: the data is not wrong, there is simply too much
of it. Keeping the first occurrence of each key preserves original arrival order,
so anything derived from row order stays stable.
"""
from __future__ import annotations

from agent.contracts import ActionRecord, ActionType
from agent.registry import actuator
from agent.tools.actuators.base import WarehouseActuator
from agent.tools.warehouse.duck import connect
from ml.config import DUCKDB_PATH

# The column that should be unique per table, mirroring the dbt `unique` tests.
DEFAULT_KEYS = {
    "raw_transactions": "transaction_id",
    "stg_transactions": "transaction_id",
    "training_dataset": "transaction_id",
    "feat_user_txn_stats": "user_id",
    "feat_merchant_risk": "merchant_id",
}


@actuator
class DedupePartitionActuator(WarehouseActuator):
    name = "dedupe_partition"
    action_type = ActionType.DEDUPE_PARTITION

    def _mutate(self, table: str, action: ActionRecord) -> str:
        key = action.params.get("key") or DEFAULT_KEYS.get(table)
        if not key:
            raise ValueError(f"dedupe needs a key column for {table}")

        con = connect(str(DUCKDB_PATH))
        try:
            before = con.execute(f'select count(*) from main."{table}"').fetchone()[0]
            distinct = con.execute(
                f'select count(distinct "{key}") from main."{table}"'
            ).fetchone()[0]
            if before == distinct:
                raise RuntimeError(f"{table} has no duplicate {key} values")

            # rowid is DuckDB's physical order, so min(rowid) is the first arrival
            con.execute(
                f'delete from main."{table}" where rowid not in '
                f'(select min(rowid) from main."{table}" group by "{key}")'
            )
            after = con.execute(f'select count(*) from main."{table}"').fetchone()[0]
        finally:
            con.close()

        return (f"deduplicated {table} on {key}: {before} -> {after} rows "
                f"({before - after} duplicate(s) removed)")
