"""Detector: the model got suspiciously good.

The exact mirror of the training-regression detector, and the more dangerous of
the two. A model whose score collapses gets noticed within the hour; a model
whose score jumps to 0.99 gets celebrated and shipped. Almost always it has
learned to read the answer — some upstream field started carrying information
derived from the label, and the model found it.

Both detectors read the same registry through ChampionMetrics, so "the champion"
means the same thing to each.
"""
from __future__ import annotations

from datetime import datetime, timezone

import datahub.emitter.mce_builder as builder

from agent.contracts import Incident, SignalType
from agent.registry import detector
from agent.tools.warehouse.champion import ROC_AUC_MAX, ChampionMetrics
from agent.tools.warehouse.profiler import (
    feature_target_correlations,
    identify_leaks,
)

TRAINING_TABLE = "training_dataset"

MODEL_URN = builder.make_ml_model_urn("mlflow", "fraud_detection_model_1", "PROD")


@detector
class LabelLeakageDetector:
    name = "label_leakage"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.champion = ChampionMetrics()

    def detect(self) -> list[Incident]:
        info = self.champion.current()
        if info is None or info.roc_auc is None or info.roc_auc <= ROC_AUC_MAX:
            return []

        from ml.config import FEATURES, TARGET

        correlations = feature_target_correlations(TRAINING_TABLE, FEATURES, TARGET)
        leaking = identify_leaks(correlations)

        evidence = {
            "metrics": info.metrics,
            "ceiling": ROC_AUC_MAX,
            "version": info.version,
            "correlations": correlations,
            "leaking_features": leaking,
        }
        if leaking:
            worst = max(leaking, key=lambda f: abs(leaking[f]))
            evidence["fix_request"] = {
                "file": "ml/config.py",
                "title": f"drop leaked feature '{worst}' from the model",
                "instruction": (
                    f"The feature '{worst}' correlates {leaking[worst]:.3f} with the "
                    f"target '{TARGET}', so it is leaking the label into training. "
                    f"Remove '{worst}' from the FEATURES list. Change nothing else."
                ),
                "detail": (f"Champion v{info.version} scored roc_auc "
                           f"{info.roc_auc:.4f}, above the {ROC_AUC_MAX} ceiling."),
            }

        detail = (f"; '{max(leaking, key=lambda f: abs(leaking[f]))}' correlates "
                  f"{max(leaking.values(), key=abs):.3f} with {TARGET}"
                  if leaking else "; no single feature identified yet")

        return [Incident(
            id=f"LEAK-v{info.version}",
            asset_urn=MODEL_URN,
            signal_type=SignalType.LABEL_LEAKAGE,
            detected_at=datetime.now(timezone.utc),
            summary=(f"champion v{info.version} scored roc_auc {info.roc_auc:.3f}, "
                     f"above the {ROC_AUC_MAX} ceiling — too good to be true"
                     + detail),
            raw_evidence=evidence,
        )]
