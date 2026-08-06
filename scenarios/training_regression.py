"""Training-regression incident: a bad training run ships a weak champion model.

Trains a deliberately degraded model (tiny sample + heavy label noise) and points
the `champion` alias at it, so its roc_auc drops below threshold. The training-
metric detector flags it. Restore a good model with:  python -m ml.train
"""
from __future__ import annotations

import numpy as np


class TrainingRegressionScenario:
    name = "training_regression"
    description = "A bad training run ships a weak champion model"

    def apply(self, reingest_after: bool = True) -> None:
        import mlflow
        import mlflow.sklearn
        import pandas as pd
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
            mlflow.sklearn.log_model(clf, artifact_path="model",
                                     registered_model_name=MODEL_NAME)

        client = mlflow.MlflowClient()
        latest = max(client.search_model_versions(f"name='{MODEL_NAME}'"),
                     key=lambda v: int(v.version))
        client.set_registered_model_alias(MODEL_NAME, CHAMPION_ALIAS, latest.version)

        print(f"[{self.name}] shipped weak champion v{latest.version} "
              f"(roc_auc={roc:.3f})")
        print(f"\n[{self.name}] done. Run `python -m agent` to detect. "
              f"Restore with `python -m ml.train`.")
