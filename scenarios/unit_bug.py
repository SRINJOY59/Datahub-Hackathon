"""Unit-bug incident: an upstream change starts reporting transaction amounts in
cents instead of dollars (a 100x scale error) for the most recent batch.

Silent: nothing errors, the pipeline keeps running, but avg_txn_amount inflates
-> the range assertion fails and the fraud model's predictions drift.
"""
from __future__ import annotations

import duckdb

from scenarios.base import Scenario


class UnitBugScenario(Scenario):
    name = "unit_bug"
    description = "Upstream reports amounts in cents (100x unit bug)"

    def inject(self, con: duckdb.DuckDBPyConnection) -> str:
        clause = self.recent_clause(con)
        before = con.execute("select avg(amount) from raw_transactions").fetchone()[0]
        con.execute(f"update raw_transactions set amount = amount * 100 where {clause}")
        n = con.execute(
            f"select count(*) from raw_transactions where {clause}"
        ).fetchone()[0]
        after = con.execute("select avg(amount) from raw_transactions").fetchone()[0]
        return (f"upstream now reports amounts in cents (100x unit bug); "
                f"corrupted {n} recent txns; raw avg {before:.2f} -> {after:.2f}")
