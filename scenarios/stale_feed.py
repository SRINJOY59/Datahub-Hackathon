"""Stale-feed incident: the upstream feed stopped delivering.

The purest silent failure in the set. Nothing is corrupted — the rows that are
there are perfectly good, there are simply no new ones. Every null check, range
check and uniqueness check passes, so **all 22 dbt assertions stay green** while
the model scores today's traffic on last week's picture of the world.

Only a freshness check comparing against a recorded baseline can see it.
"""
from __future__ import annotations

import duckdb

from scenarios.base import DataScenario, Expectation

# Drop the newest slice of history. Kept under the volume detector's tolerance so
# this scenario tests freshness specifically rather than tripping every alarm.
KEEP_QUANTILE = 0.90


class StaleFeedScenario(DataScenario):
    name = "stale_feed"
    description = "Upstream feed stopped delivering (no new rows arrive)"

    expectation = Expectation(
        signal_type="freshness",
        change_type="freshness_lag",
        root_table="raw_transactions",
        actions=["tag_asset", "pause_job"],
        checks_pass_after_act=False,   # contained, not repaired: the rows are gone
        trips_dbt_tests=False,         # the whole point — dbt stays green
        note="The agent cannot restore data that never arrived. Success here is "
             "containment: warn downstream, pause scoring, page a human.",
    )

    def inject(self, con: duckdb.DuckDBPyConnection) -> str:
        cutoff = con.execute(
            "select quantile_cont(epoch(txn_timestamp), ?) from raw_transactions",
            [KEEP_QUANTILE],
        ).fetchone()[0]
        before_max, before_rows = con.execute(
            "select max(txn_timestamp), count(*) from raw_transactions"
        ).fetchone()

        con.execute(f"delete from raw_transactions where epoch(txn_timestamp) > {cutoff}")

        after_max, after_rows = con.execute(
            "select max(txn_timestamp), count(*) from raw_transactions"
        ).fetchone()
        return (f"feed stopped delivering: newest transaction {before_max} -> "
                f"{after_max} ({before_rows - after_rows} recent rows never arrived); "
                f"every value still valid, so dbt has nothing to complain about")
