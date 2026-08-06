"""Shared config + paths for the ML layer."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DUCKDB_PATH = REPO_ROOT / "pipeline" / "dbt" / "fraud.duckdb"
MLFLOW_TRACKING_URI = (REPO_ROOT / "mlruns").as_uri()  # file:// URI

EXPERIMENT_NAME = "fraud_detection"
MODEL_NAME = "fraud_detection_model"
CHAMPION_ALIAS = "champion"

# The dbt dataset the model is trained on (its DataHub urn — used to wire lineage).
TRAINING_DATASET_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:dbt,"
    "fraud_demo.fraud.main.training_dataset,PROD)"
)

# Feature columns (order matters — score.py must match).
FEATURES = [
    "amount",
    "avg_txn_amount",
    "user_txn_count",
    "stddev_txn_amount",
    "merchant_fraud_rate",
    "merchant_txn_count",
    "is_risky_category",
]
TARGET = "is_fraud"
