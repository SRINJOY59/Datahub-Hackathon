"""Probe: what exactly moved in the model's predictions.

Turns "the model drifted" into numbers a human can argue with — how far the
positive rate shifted, and which feature moved most underneath it. The detector
already computed this to decide there was an incident; the probe's job is to put
it in front of the RCA as grounded evidence rather than making the LLM guess.
"""
from __future__ import annotations

from agent.contracts import ContextBundle, Evidence, Incident
from agent.registry import probe

_DRIFT_SIGNALS = {"model_drift"}


@probe
class PredictionDriftProbe:
    name = "prediction_drift"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        pass

    def applies_to(self, incident: Incident) -> bool:
        return incident.signal_type.value in _DRIFT_SIGNALS

    def investigate(self, incident: Incident, context: ContextBundle) -> list[Evidence]:
        ev = incident.raw_evidence or {}
        if not ev.get("reasons"):
            return []

        snapshot = ev.get("snapshot") or {}
        baseline = ev.get("baseline") or {}
        evidence = [Evidence(
            probe=self.name,
            kind="model_drift",
            summary=(f"positive-prediction rate {baseline.get('positive_pred_rate', 0):.4f} "
                     f"-> {snapshot.get('positive_pred_rate', 0):.4f} "
                     f"(Δ {ev.get('pred_rate_delta', 0):+.4f}); "
                     f"triggered by {', '.join(ev.get('reasons', []))}"),
            data={"change_type": "model_drift",
                  "pred_rate_delta": ev.get("pred_rate_delta"),
                  "mean_score_delta": ev.get("mean_score_delta")},
            confidence="high",
        )]

        worst = ev.get("worst_feature")
        drift = ev.get("feature_drift") or {}
        if worst and worst in drift:
            moved = {f: d for f, d in drift.items() if abs(d) >= 0.05}
            evidence.append(Evidence(
                probe=self.name,
                kind="feature_shift",
                summary=(f"largest feature move: {worst} "
                         f"{drift[worst] * 100:+.1f}% vs the scoring baseline"
                         + (f"; {len(moved)} feature(s) moved >5%" if moved else "")),
                data={"worst_feature": worst, "feature_drift": drift},
                confidence="high",
            ))
        return evidence
