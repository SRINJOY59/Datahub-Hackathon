"""Null-spike incident: an upstream change drops the transaction amount value for
the most recent batch, sending NULLs into the pipeline.

Trips the not_null assertion on amount and corrupts avg_txn_amount for affected
users.
"""
from __future__ import annotations

import duckdb

from scenarios.base import Scenario


class NullSpikeScenario(Scenario):
    name = "null_spike"
    description = "Upstream drops the amount value (null-spike)"

    def inject(self, con: duckdb.DuckDBPyConnection) -> str:
        clause = self.recent_clause(con)
        con.execute(f"update raw_transactions set amount = null where {clause}")
        n = con.execute(
            f"select count(*) from raw_transactions where {clause}"
        ).fetchone()[0]
        return f"upstream dropped the amount value (null-spike); nulled {n} recent txns"
