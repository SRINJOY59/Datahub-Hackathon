"""Detector: ML training-metric regression.

Reads the champion model's evaluation metrics from MLflow and flags a regression
when they fall below threshold — the universal "the model got worse" incident for
ML/LLM training pipelines (eval-metric drop, reward-model regression, etc.).

Fast: reads logged run metrics, no re-scoring.
"""
from __future__ import annotations

from datetime import datetime, timezone

import datahub.emitter.mce_builder as builder

from agent.contracts import Incident, SignalType

ROC_AUC_MIN = 0.65  # below this, the champion is considered regressed
MODEL_URN = builder.make_ml_model_urn("mlflow", "fraud_detection_model_1", "PROD")

# Note: this detector is registered lazily to avoid importing mlflow at module
# import time for environments that don't need it.
from agent.registry import detector  # noqa: E402


@detector
class TrainingMetricDetector:
    name = "training_metrics"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        pass

    def detect(self) -> list[Incident]:
        try:
            import mlflow
            from ml.config import CHAMPION_ALIAS, MLFLOW_TRACKING_URI, MODEL_NAME

            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            client = mlflow.MlflowClient()
            mv = client.get_model_version_by_alias(MODEL_NAME, CHAMPION_ALIAS)
            metrics = client.get_run(mv.run_id).data.metrics
        except Exception:
            return []

        roc = metrics.get("roc_auc")
        if roc is None or roc >= ROC_AUC_MIN:
            return []

        return [Incident(
            id=f"MLR-v{mv.version}",
            asset_urn=MODEL_URN,
            signal_type=SignalType.TRAINING_REGRESSION,
            detected_at=datetime.now(timezone.utc),
            summary=(f"champion model v{mv.version} regressed: roc_auc={roc:.3f} "
                     f"< {ROC_AUC_MIN} threshold"),
            raw_evidence={"metrics": metrics, "threshold": ROC_AUC_MIN,
                          "version": mv.version},
        )]
