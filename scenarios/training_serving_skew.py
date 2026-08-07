"""Training/serving-skew incident: the model is sound, its inputs have moved.

Nothing here is broken and nothing is wrong. The model is the one that was
validated, the data passes every assertion, and the scoring run looks stable
against the last one. What has changed is the gap between the distribution the
model was *fitted* to and the distribution it is now being *asked about* — the
slow, quiet way models stop being right.

The scenario is careful to isolate exactly that signal:

  1. train a champion on the current, clean data, recording its feature means
  2. shift the world underneath it
  3. re-score **and move the scoring baseline with it**

Step 3 is what makes this distinct from `model_drift`. With the baseline moved,
run-to-run drift is zero — the only remaining discrepancy is against training,
which is the definition of skew. Rolling the model back would achieve nothing
here; it needs retraining on data that looks like today.
"""
from __future__ import annotations

from scenarios.base import (
    DUCKDB_PATH,
    Expectation,
    ModelScenario,
    rescore,
    retrain,
    run_dbt,
)

SHIFT = 1.6


class TrainingServingSkewScenario(ModelScenario):
    name = "training_serving_skew"
    description = "Serving features drift away from the training distribution"

    expectation = Expectation(
        signal_type="training_serving_skew",
        change_type="training_serving_skew",
        actions=["tag_asset", "pause_job"],
        checks_pass_after_act=False,   # contained: only retraining truly fixes it
        trips_dbt_tests=False,
        note="Containment, not repair. The model is fine and the data is fine; "
             "they simply no longer describe the same world.",
    )

    def perturb(self) -> str:
        import duckdb

        from agent.tools.warehouse.duck import connect

        print(f"[{self.name}] training a champion on the current data "
              f"(records its feature means)...")
        retrain()

        con = connect(str(DUCKDB_PATH))
        try:
            before = con.execute(
                "select avg(amount) from raw_transactions"
            ).fetchone()[0]
            con.execute(f"update raw_transactions set amount = amount * {SHIFT}")
            after = con.execute(
                "select avg(amount) from raw_transactions"
            ).fetchone()[0]
        finally:
            con.close()

        print(f"\n[{self.name}] rebuilding models on the shifted data...")
        run_dbt(["run"])

        print(f"\n[{self.name}] re-scoring and moving the baseline with it "
              f"(so run-to-run drift is zero and only skew remains)...")
        scored = rescore(update_baseline=True)

        return (f"serving distribution moved away from training: mean amount "
                f"{before:.2f} -> {after:.2f} ({SHIFT}x) while the champion stays "
                f"fitted to the old one; {scored}")

    def cleanup(self) -> None:
        """Nothing to undo beyond the warehouse re-seed and champion restore that
        PipelineReset already performs; the model trained here is a good one."""
        return None
