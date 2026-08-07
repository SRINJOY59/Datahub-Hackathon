"""Probe: how far serving has drifted from what the model learned.

Reports each feature's training mean beside its current serving mean, so the RCA
can say which inputs moved and by how much. That distinction matters for the
remediation: a model whose inputs have moved is not a broken model, and rolling
it back would achieve nothing — the honest recommendation is to retrain on data
that looks like today.
"""
from __future__ import annotations

from agent.contracts import ContextBundle, Evidence, Incident
from agent.registry import probe

_SKEW_SIGNALS = {"training_serving_skew"}


@probe
class TrainingServingSkewProbe:
    name = "training_serving_skew"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        pass

    def applies_to(self, incident: Incident) -> bool:
        return incident.signal_type.value in _SKEW_SIGNALS

    def investigate(self, incident: Incident, context: ContextBundle) -> list[Evidence]:
        ev = incident.raw_evidence or {}
        skewed = ev.get("skewed_features") or {}
        if not skewed:
            return []

        train = ev.get("train_means") or {}
        serve = ev.get("serve_means") or {}

        evidence = [Evidence(
            probe=self.name,
            kind="training_serving_skew",
            summary=(f"{feature}: trained on mean {train.get(feature, 0):.2f}, "
                     f"now serving mean {serve.get(feature, 0):.2f} "
                     f"({shift:+.0%})"),
            data={"feature": feature, "change_type": "training_serving_skew",
                  "train_mean": train.get(feature), "serve_mean": serve.get(feature),
                  "shift": shift},
            confidence="high",
        ) for feature, shift in sorted(skewed.items(), key=lambda kv: -abs(kv[1]))]

        evidence.append(Evidence(
            probe=self.name,
            kind="skew_summary",
            summary=(f"{len(skewed)} of {len(train)} feature(s) sit more than "
                     f"{ev.get('tolerance', 0):.0%} from champion "
                     f"v{ev.get('version')}'s training distribution — the model is "
                     f"sound, its inputs have moved"),
            data={"skewed": skewed, "version": ev.get("version")},
            confidence="high",
        ))
        return evidence
