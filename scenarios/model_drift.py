"""Model-drift incident: the world moved, and the model's answers moved with it.

A uniform repricing — every transaction amount 40% higher. Nothing is wrong with
the data: no nulls, no implausible values, and because the shift is uniform the
recent-versus-historical trip-wire sees no change at all, so **all 22 dbt
assertions stay green**. The model keeps scoring, and quietly starts saying
something different than it used to.

The only trace is in the predictions themselves, which is why this needs the
scoring snapshot rather than the warehouse to detect.
"""
from __future__ import annotations

import duckdb

from scenarios.base import DataScenario, Expectation, rescore

SHIFT = 1.4


class ModelDriftScenario(DataScenario):
    name = "model_drift"
    description = "Uniform repricing shifts predictions without breaking any test"

    expectation = Expectation(
        signal_type="model_drift",
        change_type="model_drift",
        actions=["tag_asset", "repoint_model"],
        checks_pass_after_act=True,
        trips_dbt_tests=False,
        note="Uniform, so the recent-vs-historical assertion cannot see it. "
             "Detected from the prediction distribution, not the data.",
    )

    def inject(self, con: duckdb.DuckDBPyConnection) -> str:
        before = con.execute("select avg(amount) from raw_transactions").fetchone()[0]
        # Applied to every row: a shift that is uniform in time is invisible to
        # any check that compares recent data against older data.
        con.execute(f"update raw_transactions set amount = amount * {SHIFT}")
        after = con.execute("select avg(amount) from raw_transactions").fetchone()[0]
        return (f"uniform repricing: mean amount {before:.2f} -> {after:.2f} "
                f"({SHIFT}x across the whole history, so recent-vs-historical "
                f"comparisons see nothing)")

    def post_build(self) -> str:
        # Baseline deliberately left alone — the gap between this scoring run and
        # the last known-good one is the incident.
        return rescore(update_baseline=False)
