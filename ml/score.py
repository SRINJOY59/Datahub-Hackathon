"""Score 'live' traffic with the champion fraud model and emit a drift signal.

This simulates the deployed model. Each run:
  - loads the champion model from the MLflow registry,
  - scores the current feature state (training_dataset in DuckDB),
  - records the prediction distribution + feature means as a snapshot,
  - compares against the saved baseline to surface drift.

A large jump in the positive-prediction rate or a shift in feature means is the
silent-failure signal the agent reacts to.

Run:  python ml/score.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import mlflow
import mlflow.sklearn
import pandas as pd

import duckdb

from ml.config import (
    CHAMPION_ALIAS,
    DUCKDB_PATH,
    FEATURES,
    MLFLOW_TRACKING_URI,
    MODEL_NAME,
    REPO_ROOT,
)

BASELINE_PATH = REPO_ROOT / "ml" / "baseline.json"
SNAPSHOT_PATH = REPO_ROOT / "ml" / "last_scoring_snapshot.json"
PRED_DRIFT_THRESHOLD = 0.02      # +/-2pp positive-rate shift
FEATURE_DRIFT_THRESHOLD = 0.25   # +/-25% relative shift in any feature mean


def load_features() -> pd.DataFrame:
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        return con.execute(f"select {', '.join(FEATURES)} from training_dataset").df()
    finally:
        con.close()


def score() -> dict:
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}@{CHAMPION_ALIAS}")

    X = load_features()
    proba = model.predict_proba(X)[:, 1]
    preds = (proba >= 0.5).astype(int)

    return {
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "model": f"{MODEL_NAME}@{CHAMPION_ALIAS}",
        "n_scored": int(len(X)),
        "positive_pred_rate": float(preds.mean()),
        "mean_score": float(proba.mean()),
        "feature_means": {c: float(X[c].mean()) for c in FEATURES},
    }


def main() -> None:
    snap = score()
    SNAPSHOT_PATH.write_text(json.dumps(snap, indent=2))

    if not BASELINE_PATH.exists():
        BASELINE_PATH.write_text(json.dumps(snap, indent=2))
        print("No baseline found — saved current snapshot as baseline.")
        base = snap
    else:
        base = json.loads(BASELINE_PATH.read_text())

    dr = snap["positive_pred_rate"] - base["positive_pred_rate"]
    dscore = snap["mean_score"] - base["mean_score"]

    # per-feature relative drift vs baseline
    feature_drift = {}
    for c in FEATURES:
        b = base["feature_means"][c]
        cur = snap["feature_means"][c]
        feature_drift[c] = (cur - b) / b if b else 0.0
    worst_feat = max(feature_drift, key=lambda c: abs(feature_drift[c]))

    print(f"\nScored {snap['n_scored']} txns with {snap['model']}")
    print(f"  positive_pred_rate: {snap['positive_pred_rate']:.4f} "
          f"(baseline {base['positive_pred_rate']:.4f}, Δ {dr:+.4f})")
    print(f"  mean_score:         {snap['mean_score']:.4f} (Δ {dscore:+.4f})")
    print(f"  top feature drift:  {worst_feat} "
          f"{feature_drift[worst_feat]*100:+.1f}%  "
          f"({base['feature_means'][worst_feat]:.2f} -> "
          f"{snap['feature_means'][worst_feat]:.2f})")

    pred_drift = abs(dr) >= PRED_DRIFT_THRESHOLD
    feat_drift = abs(feature_drift[worst_feat]) >= FEATURE_DRIFT_THRESHOLD
    drifted = pred_drift or feat_drift

    reasons = []
    if pred_drift:
        reasons.append("prediction-rate shift")
    if feat_drift:
        reasons.append(f"{worst_feat} distribution shift")
    print(f"\n  DRIFT DETECTED: {drifted}"
          + (f"  <-- incident signal ({', '.join(reasons)})" if drifted else ""))


if __name__ == "__main__":
    main()
