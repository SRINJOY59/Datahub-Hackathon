"""Drift computation, shared by the scoring job and the drift detector.

The scoring job and the agent must agree on what "drifted" means, or the agent
will explain incidents the pipeline never reported (or miss ones it did). So the
comparison and its thresholds live here, and both import them.

Two references are possible and they answer different questions:
  * baseline  — how does today's scoring compare to the last known-good scoring
                run? (silent model rot)
  * training  — how do serve-time features compare to the distribution the model
                was trained on? (training/serving skew)
This module handles the first; the second reuses `relative_shift`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PRED_DRIFT_THRESHOLD = 0.02      # +/-2pp positive-rate shift
FEATURE_DRIFT_THRESHOLD = 0.25   # +/-25% relative shift in any feature mean


@dataclass
class DriftReport:
    """Everything the scoring printout and the detector both need."""
    drifted: bool = False
    pred_rate_delta: float = 0.0
    mean_score_delta: float = 0.0
    feature_drift: dict[str, float] = field(default_factory=dict)
    worst_feature: str = ""
    worst_feature_delta: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def pred_drift(self) -> bool:
        return abs(self.pred_rate_delta) >= PRED_DRIFT_THRESHOLD

    @property
    def feature_drift_detected(self) -> bool:
        return abs(self.worst_feature_delta) >= FEATURE_DRIFT_THRESHOLD

    def summary(self) -> str:
        if not self.drifted:
            return "no drift against baseline"
        return (f"{', '.join(self.reasons)}; positive-rate Δ "
                f"{self.pred_rate_delta:+.4f}, worst feature {self.worst_feature} "
                f"{self.worst_feature_delta * 100:+.1f}%")


def relative_shift(current: float, reference: float) -> float:
    """Signed relative change, safe when the reference is zero."""
    return (current - reference) / reference if reference else 0.0


def compute_drift(snapshot: dict, baseline: dict) -> DriftReport:
    """Compare a scoring snapshot against a baseline snapshot.

    Both are the dicts written by ml/score.py: positive_pred_rate, mean_score,
    and feature_means.
    """
    report = DriftReport()
    if not snapshot or not baseline:
        return report

    report.pred_rate_delta = (snapshot.get("positive_pred_rate", 0.0)
                              - baseline.get("positive_pred_rate", 0.0))
    report.mean_score_delta = (snapshot.get("mean_score", 0.0)
                               - baseline.get("mean_score", 0.0))

    snap_means = snapshot.get("feature_means") or {}
    base_means = baseline.get("feature_means") or {}
    report.feature_drift = {
        col: relative_shift(snap_means[col], base_means[col])
        for col in snap_means if col in base_means
    }

    if report.feature_drift:
        report.worst_feature = max(report.feature_drift,
                                   key=lambda c: abs(report.feature_drift[c]))
        report.worst_feature_delta = report.feature_drift[report.worst_feature]

    if report.pred_drift:
        report.reasons.append("prediction-rate shift")
    if report.feature_drift_detected:
        report.reasons.append(f"{report.worst_feature} distribution shift")
    report.drifted = bool(report.reasons)
    return report
