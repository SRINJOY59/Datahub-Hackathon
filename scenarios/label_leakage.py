"""Label-leakage incident: the model learned to read the answer.

An upstream change starts folding a fraud-review surcharge into the transaction
amount, so `amount` now carries information that only exists *because* a
transaction was fraudulent. Retrained on that, the model's `roc_auc` jumps toward
1.0 and every dashboard says it has never been better.

This is the most dangerous incident in the set precisely because it looks like
success. A detector that only watches for metrics falling would wave it through
and the model would ship, learning nothing generalisable at all.

The surcharge is applied across the whole history, so the recent-versus-
historical trip-wire sees a stable distribution and **all 22 dbt assertions stay
green**.
"""
from __future__ import annotations

import duckdb

from scenarios.base import DataScenario, Expectation, retrain

# Large enough to dominate the natural spread in `amount`, so the correlation
# with the label becomes unmistakable.
FRAUD_SURCHARGE = 500.0


class LabelLeakageScenario(DataScenario):
    name = "label_leakage"
    description = "A label-derived surcharge leaks into a feature; roc_auc soars"

    expectation = Expectation(
        signal_type="label_leakage",
        change_type="label_leakage",
        root_table="training_dataset",
        root_column="amount",
        actions=["pause_job", "tag_asset"],
        checks_pass_after_act=False,   # contained: the leak is in the data
        trips_dbt_tests=False,
        note="The mirror of a regression: the metric goes UP. Nothing the agent "
             "can do resolves this — every earlier model was fitted to a "
             "distribution the leaked feature no longer matches — so it stops "
             "serving, warns downstream, and proposes the diff that removes the "
             "feature. Repairing it needs a code change and a retrain.",
    )

    def inject(self, con: duckdb.DuckDBPyConnection) -> str:
        before = con.execute(
            "select corr(amount, is_fraud) from raw_transactions"
        ).fetchone()[0] or 0.0
        con.execute(
            f"update raw_transactions "
            f"set amount = amount + is_fraud * {FRAUD_SURCHARGE}"
        )
        after = con.execute(
            "select corr(amount, is_fraud) from raw_transactions"
        ).fetchone()[0] or 0.0
        return (f"fraud surcharge folded into `amount`: correlation with the label "
                f"{before:+.3f} -> {after:+.3f}; the feature now encodes the "
                f"outcome it is meant to predict")

    def post_build(self) -> str:
        # The leak only becomes an incident once a model has learned from it.
        return retrain()
