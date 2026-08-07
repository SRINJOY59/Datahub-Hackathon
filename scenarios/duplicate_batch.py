"""Duplicate-batch incident: upstream delivered the same batch twice.

A retry that was not idempotent. Nothing is corrupted and nothing is missing —
there is simply twice as much of one window, so every per-user aggregate counts
those transactions twice and the model trains on a skewed picture of behaviour.

Unlike the other silent scenarios this one *is* caught by an existing assertion:
the uniqueness test on `transaction_id`. What it needs is a remediation that
repairs rather than rolls back, since the correct data is present — just twice.
"""
from __future__ import annotations

import duckdb

from scenarios.base import DataScenario, Expectation


class DuplicateBatchScenario(DataScenario):
    name = "duplicate_batch"
    description = "Upstream re-delivered a recent batch (non-idempotent retry)"
    recent_fraction = 0.20

    expectation = Expectation(
        signal_type="assertion_failure",
        change_type="duplicate_records",
        root_table="raw_transactions",
        root_column="transaction_id",
        actions=["dedupe_partition", "tag_asset"],
        checks_pass_after_act=True,
        trips_dbt_tests=True,        # the uniqueness assertion catches this one
        note="Repaired by removing the duplicates, not by rolling back — the "
             "first copy of every row is legitimate data.",
    )

    def inject(self, con: duckdb.DuckDBPyConnection) -> str:
        clause = self.recent_clause(con)
        before = con.execute("select count(*) from raw_transactions").fetchone()[0]
        con.execute(
            f"insert into raw_transactions select * from raw_transactions "
            f"where {clause}"
        )
        after = con.execute("select count(*) from raw_transactions").fetchone()[0]
        return (f"upstream re-delivered a batch: {before} -> {after} rows "
                f"({after - before} duplicated transaction_ids); per-user "
                f"aggregates now double-count that window")
