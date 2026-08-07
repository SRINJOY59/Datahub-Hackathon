"""Volume-collapse incident: the batch arrived at a fraction of its size.

A partial delivery. Every row present is correct, so nulls, ranges and
uniqueness all pass and **all 22 dbt assertions stay green** — there are simply
far fewer rows than there should be. Averages are now computed over a sliver of
the population and the model trains on what is left.

The newest row is deliberately preserved, so this reads as a thin delivery rather
than a stopped one and the freshness detector stays quiet. Volume is the signal
under test.
"""
from __future__ import annotations

import duckdb

from scenarios.base import DataScenario, Expectation

DROP_FRACTION = 0.60


class VolumeCollapseScenario(DataScenario):
    name = "volume_collapse"
    description = "Batch delivered at a fraction of its usual size"

    expectation = Expectation(
        signal_type="volume_anomaly",
        change_type="volume_anomaly",
        root_table="raw_transactions",
        actions=["pin_feature", "tag_asset"],
        checks_pass_after_act=True,   # the missing rows exist in the snapshot
        trips_dbt_tests=False,        # counting is the one thing dbt never does
        note="Repairable: the rows are absent from the live table but present in "
             "the last-good snapshot, so pinning restores them.",
    )

    def inject(self, con: duckdb.DuckDBPyConnection) -> str:
        before = con.execute("select count(*) from raw_transactions").fetchone()[0]

        # Spread the loss across the whole history, and keep the newest row, so
        # this is unmistakably a thin batch rather than a feed that stopped.
        con.execute(
            f"delete from raw_transactions where random() < {DROP_FRACTION} "
            f"and txn_timestamp < (select max(txn_timestamp) from raw_transactions)"
        )

        after = con.execute("select count(*) from raw_transactions").fetchone()[0]
        return (f"batch arrived thin: {before} -> {after} rows "
                f"({(after - before) / before:+.0%}); every remaining row is valid, "
                f"so no assertion notices anything is missing")
