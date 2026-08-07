"""Training-regression incident: a bad training run ships a weak champion model.

Trains a deliberately degraded model (tiny sample + heavy label noise) and points
the `champion` alias at it, so its roc_auc drops below threshold. The training-
metric detector flags it.

cleanup() re-points `champion` at the best healthy version, so a reset restores a
good model without the operator having to remember to re-run training.
"""
from __future__ import annotations

import numpy as np

from scenarios.base import Expectation, ModelScenario


class TrainingRegressionScenario(ModelScenario):
    name = "training_regression"
    description = "A bad training run ships a weak champion model"

    expectation = Expectation(
        signal_type="training_regression",
        change_type="training_regression",
        actions=["repoint_model"],
        trips_dbt_tests=False,   # the warehouse is clean; the model is not
        note="Detected from MLflow metrics, not from data.",
    )

    def perturb(self) -> str:
        import mlflow
        import mlflow.sklearn
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.metrics import roc_auc_score
        from sklearn.model_selection import train_test_split

        import duckdb
        from ml.config import (CHAMPION_ALIAS, DUCKDB_PATH, EXPERIMENT_NAME,
                               FEATURES, MLFLOW_TRACKING_URI, MODEL_NAME, TARGET)

        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment(EXPERIMENT_NAME)

        con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
        df = con.execute(
            f"select {', '.join(FEATURES + [TARGET])} from training_dataset"
        ).df()
        con.close()

        # degrade: tiny sample + 40% label noise
        rng = np.random.default_rng(0)
        df = df.sample(frac=0.05, random_state=0).reset_index(drop=True)
        flip = rng.random(len(df)) < 0.40
        df.loc[flip, TARGET] = 1 - df.loc[flip, TARGET]

        X, y = df[FEATURES], df[TARGET]
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.3, random_state=0)

        with mlflow.start_run(run_name="fraud_gbc_BAD"):
            clf = GradientBoostingClassifier(n_estimators=10, max_depth=1, random_state=0)
            clf.fit(X_tr, y_tr)
            roc = roc_auc_score(y_te, clf.predict_proba(X_te)[:, 1])
            mlflow.log_metric("roc_auc", roc)
            mlflow.set_tag("scenario", "training_regression")
            # deliberately NOT tagged validation_status=passed — that tag is what
            # the Time Machine uses to find a version worth rolling back to.
            mlflow.sklearn.log_model(clf, artifact_path="model",
                                     registered_model_name=MODEL_NAME)

        client = mlflow.MlflowClient()
        latest = max(client.search_model_versions(f"name='{MODEL_NAME}'"),
                     key=lambda v: int(v.version))
        client.set_registered_model_alias(MODEL_NAME, CHAMPION_ALIAS, latest.version)

        return (f"shipped weak champion v{latest.version} (roc_auc={roc:.3f}); "
                f"restore with `python -m scenarios reset` or `python -m ml.train`")

    def cleanup(self) -> None:
        """Point `champion` back at the newest version worth serving.

        "Passed validation" alone is not enough: every training run writes that
        tag, including one that scored 0.998 because the label leaked into a
        feature. A restore that picked the highest-scoring validated version
        would happily reinstate the very model another scenario just removed, so
        this reuses the same healthy-band check the Time Machine rolls back with.
        """
        try:
            from agent.tools.warehouse.champion import ChampionMetrics

            champion = ChampionMetrics()
            current = champion.current()
            if current is not None and current.validated and current.healthy:
                return  # already serving something sound

            best = champion.last_good(
                exclude_version=current.version if current else None)
            if best is None or (current and best.version == current.version):
                return
            if champion.set_alias(best.version):
                print(f"[reset] champion restored: "
                      f"v{current.version if current else '?'} -> v{best.version}")
        except Exception:
            return  # no MLflow / no registry yet — nothing to restore
