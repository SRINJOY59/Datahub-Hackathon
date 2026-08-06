"""Train the fraud-detection model on the dbt `training_dataset` and register it
in the MLflow Model Registry with a `champion` alias.

Each run:
  - reads features from DuckDB (built by dbt),
  - trains a gradient-boosted classifier,
  - logs params + metrics + the training-data reference to MLflow,
  - registers a new model version and points the `champion` alias at it.

Run:  python ml/train.py
"""
from __future__ import annotations

import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.models.signature import infer_signature
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

import duckdb

from ml.config import (
    CHAMPION_ALIAS,
    DUCKDB_PATH,
    EXPERIMENT_NAME,
    FEATURES,
    MLFLOW_TRACKING_URI,
    MODEL_NAME,
    TARGET,
)


def load_training_data() -> pd.DataFrame:
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        df = con.execute(
            f"select {', '.join(FEATURES + [TARGET])} from training_dataset"
        ).df()
    finally:
        con.close()
    return df


def main() -> None:
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    df = load_training_data()
    X, y = df[FEATURES], df[TARGET]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )

    with mlflow.start_run(run_name="fraud_gbc") as run:
        # Record the training-data lineage (surfaced by DataHub's MLflow source).
        dataset = mlflow.data.from_pandas(
            df, source=str(DUCKDB_PATH), name="training_dataset", targets=TARGET
        )
        mlflow.log_input(dataset, context="training")

        params = {"n_estimators": 200, "max_depth": 3, "learning_rate": 0.1}
        clf = GradientBoostingClassifier(random_state=42, **params)
        clf.fit(X_train, y_train)

        proba = clf.predict_proba(X_test)[:, 1]
        preds = (proba >= 0.5).astype(int)
        metrics = {
            "roc_auc": roc_auc_score(y_test, proba),
            "pr_auc": average_precision_score(y_test, proba),
            "precision": precision_score(y_test, preds, zero_division=0),
            "recall": recall_score(y_test, preds, zero_division=0),
            "f1": f1_score(y_test, preds, zero_division=0),
            "fraud_rate": float(y.mean()),
            "positive_pred_rate": float(preds.mean()),
        }

        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.set_tag("domain", "fraud_detection")
        mlflow.set_tag("feature_set", ",".join(FEATURES))

        signature = infer_signature(X_test, preds)
        mlflow.sklearn.log_model(
            clf,
            artifact_path="model",
            signature=signature,
            registered_model_name=MODEL_NAME,
            input_example=X_test.head(3),
        )

        print(f"Run {run.info.run_id} metrics:")
        for k, v in metrics.items():
            print(f"  {k:20s} {v:.4f}")

    # Point the `champion` alias at the newest version.
    client = mlflow.MlflowClient()
    versions = client.search_model_versions(f"name='{MODEL_NAME}'")
    latest = max(versions, key=lambda v: int(v.version))
    client.set_registered_model_alias(MODEL_NAME, CHAMPION_ALIAS, latest.version)
    client.set_model_version_tag(
        MODEL_NAME, latest.version, "validation_status", "passed"
    )
    print(f"\nRegistered {MODEL_NAME} v{latest.version} -> @{CHAMPION_ALIAS}")


if __name__ == "__main__":
    main()
