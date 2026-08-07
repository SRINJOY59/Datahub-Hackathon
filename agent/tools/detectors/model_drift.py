"""Detector: the model's predictions have moved.

Silent model rot. No assertion fails, no column is out of range, the features are
all perfectly plausible — the model has simply started saying something different
than it used to. Without this the only way anyone notices is when the business
metric it drives moves, weeks later.

The comparison is the same one the scoring job prints, through `ml/drift.py`, so
the agent and the pipeline cannot disagree about whether something drifted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import datahub.emitter.mce_builder as builder

from agent.contracts import Incident, SignalType
from agent.registry import detector
from ml.drift import compute_drift

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = REPO_ROOT / "ml" / "baseline.json"
SNAPSHOT_PATH = REPO_ROOT / "ml" / "last_scoring_snapshot.json"

MODEL_URN = builder.make_ml_model_urn("mlflow", "fraud_detection_model_1", "PROD")


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@detector
class ModelDriftDetector:
    name = "model_drift"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        pass

    def detect(self) -> list[Incident]:
        snapshot, baseline = _load(SNAPSHOT_PATH), _load(BASELINE_PATH)
        if not snapshot or not baseline:
            return []  # nothing scored yet, or no reference to compare against

        report = compute_drift(snapshot, baseline)
        if not report.drifted:
            return []

        return [Incident(
            id=f"DRIFT-{abs(hash(snapshot.get('scored_at', ''))) % 10000:04d}",
            asset_urn=MODEL_URN,
            signal_type=SignalType.MODEL_DRIFT,
            detected_at=datetime.now(timezone.utc),
            summary=(f"prediction drift on {snapshot.get('model', 'champion')}: "
                     f"{report.summary()}"),
            raw_evidence={
                "snapshot": snapshot,
                "baseline": baseline,
                "pred_rate_delta": report.pred_rate_delta,
                "mean_score_delta": report.mean_score_delta,
                "feature_drift": report.feature_drift,
                "worst_feature": report.worst_feature,
                "worst_feature_delta": report.worst_feature_delta,
                "reasons": report.reasons,
            },
        )]
