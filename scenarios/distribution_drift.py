"""Distribution-drift incident: a subtle ~2x upward shift in recent transaction
amounts. No nulls, no hard range violation — the kind of silent drift a naive
null/range check misses but the profiler catches (recent mean vs historical).
"""
from __future__ import annotations

import duckdb

from scenarios.base import Scenario


class DistributionDriftScenario(Scenario):
    name = "distribution_drift"
    description = "Subtle ~2x upward shift in recent amounts (no hard violation)"
    recent_fraction = 0.25

    def inject(self, con: duckdb.DuckDBPyConnection) -> str:
        clause = self.recent_clause(con)
        before = con.execute("select avg(amount) from raw_transactions").fetchone()[0]
        con.execute(f"update raw_transactions set amount = amount * 2.0 where {clause}")
        after = con.execute("select avg(amount) from raw_transactions").fetchone()[0]
        return (f"recent transaction amounts drifted ~2x upward "
                f"(raw avg {before:.2f} -> {after:.2f}); no nulls, no hard bound "
                f"violation")
