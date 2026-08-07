"""Detector: the model is being asked about a different world than it learned on.

Nothing here is broken. The data is valid, the assertions pass, the model is the
one that was validated — but the feature distributions it is scoring have moved
away from the ones it was fitted to, so its confidence no longer means what it
did. This is the failure that quietly erodes a model over months.

Distinct from model drift, and the difference is the reference point: drift
compares today's scoring to the last known-good *scoring run*, while skew compares
it to the *training* distribution. A model can be perfectly stable run-to-run and
still be far from where it started.
"""
from __future__ import annotations

from datetime import datetime, timezone

import datahub.emitter.mce_builder as builder

from agent.contracts import Incident, SignalType
from agent.registry import detector
from agent.tools.detectors.model_drift import SNAPSHOT_PATH, _load
from agent.tools.warehouse.champion import ChampionMetrics
from ml.drift import relative_shift

# How far a feature mean may sit from its training value before serving on it is
# no longer justified by what the model actually learned.
SKEW_TOLERANCE = 0.30

MODEL_URN = builder.make_ml_model_urn("mlflow", "fraud_detection_model_1", "PROD")


@detector
class TrainingServingSkewDetector:
    name = "training_serving_skew"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.champion = ChampionMetrics()

    def detect(self) -> list[Incident]:
        info = self.champion.current()
        if info is None:
            return []

        train_means = self.champion.training_feature_means(info)
        if not train_means:
            return []  # this champion predates per-feature logging

        snapshot = _load(SNAPSHOT_PATH)
        serve_means = (snapshot or {}).get("feature_means") or {}
        if not serve_means:
            return []

        skew = {
            f: relative_shift(serve_means[f], train_means[f])
            for f in train_means if f in serve_means
        }
        skewed = {f: s for f, s in skew.items() if abs(s) >= SKEW_TOLERANCE}
        if not skewed:
            return []

        worst = max(skewed, key=lambda f: abs(skewed[f]))

        return [Incident(
            id=f"SKEW-v{info.version}",
            asset_urn=MODEL_URN,
            signal_type=SignalType.TRAINING_SERVING_SKEW,
            detected_at=datetime.now(timezone.utc),
            summary=(f"serving features have drifted from champion v{info.version}'s "
                     f"training distribution: {worst} {skewed[worst]:+.0%} "
                     f"({train_means[worst]:.2f} at train time vs "
                     f"{serve_means[worst]:.2f} now); {len(skewed)} feature(s) skewed"),
            raw_evidence={
                "version": info.version,
                "train_means": train_means,
                "serve_means": serve_means,
                "skew": skew,
                "skewed_features": skewed,
                "tolerance": SKEW_TOLERANCE,
            },
        )]
