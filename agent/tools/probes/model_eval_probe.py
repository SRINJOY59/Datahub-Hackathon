"""Probe: for a training-regression / model-drift incident, report the model's
evaluation metrics vs. threshold as grounded evidence.
"""
from __future__ import annotations

from agent.contracts import ContextBundle, Evidence, Incident
from agent.registry import probe

_ML_SIGNALS = {"training_regression", "model_drift"}


@probe
class ModelEvalProbe:
    name = "model_eval"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        pass

    def applies_to(self, incident: Incident) -> bool:
        return incident.signal_type.value in _ML_SIGNALS

    def investigate(self, incident: Incident, context: ContextBundle) -> list[Evidence]:
        ev = incident.raw_evidence or {}
        metrics = ev.get("metrics", {})
        threshold = ev.get("threshold")
        if not metrics:
            return []
        keys = ["roc_auc", "pr_auc", "precision", "recall", "f1"]
        shown = {k: round(metrics[k], 4) for k in keys if k in metrics}
        return [Evidence(
            probe=self.name,
            kind="training_regression",
            summary=(f"champion metrics {shown}; roc_auc below threshold "
                     f"{threshold}" if threshold else f"champion metrics {shown}"),
            data={"metrics": metrics, "threshold": threshold},
            confidence="high",
        )]
