"""Probe: which feature is carrying the answer.

"The model is too accurate" is a suspicion. "`amount` correlates 0.97 with
`is_fraud` in the training table" is a finding someone can act on — it names the
column to remove and the number that justifies removing it.

Correlations are recomputed here rather than trusted from the detector, so the
evidence in the RCA reflects the data as it stands at investigation time.
"""
from __future__ import annotations

import datahub.emitter.mce_builder as builder

from agent.contracts import ContextBundle, Evidence, Incident
from agent.registry import probe
from agent.tools.warehouse.profiler import (
    feature_target_correlations,
    identify_leaks,
)

_LEAKAGE_SIGNALS = {"label_leakage"}
TRAINING_TABLE = "training_dataset"

# The leak shows up in the training table, whatever asset the incident was
# raised against — the incident itself points at the model.
TRAINING_URN = builder.make_dataset_urn(
    "dbt", f"fraud_demo.fraud.main.{TRAINING_TABLE}", "PROD")


@probe
class FeatureTargetCorrelationProbe:
    name = "feature_target_correlation"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        pass

    def applies_to(self, incident: Incident) -> bool:
        return incident.signal_type.value in _LEAKAGE_SIGNALS

    def investigate(self, incident: Incident, context: ContextBundle) -> list[Evidence]:
        from ml.config import FEATURES, TARGET

        correlations = feature_target_correlations(TRAINING_TABLE, FEATURES, TARGET)
        if not correlations:
            return []

        evidence: list[Evidence] = []
        leaking = identify_leaks(correlations)

        for feature, corr in sorted(leaking.items(), key=lambda kv: -abs(kv[1])):
            evidence.append(Evidence(
                probe=self.name,
                kind="label_leakage",
                summary=(f"{TRAINING_TABLE}.{feature} correlates {corr:+.3f} with "
                         f"the target {TARGET} — the model can read the answer "
                         f"from it"),
                data={
                    "table": TRAINING_TABLE,
                    "column": feature,
                    "dataset_urn": TRAINING_URN,
                    "change_type": "label_leakage",
                    "depth": 0,
                    "correlation": corr,
                },
                confidence="high",
            ))

        ranked = ", ".join(f"{f}={c:+.2f}" for f, c in
                           sorted(correlations.items(), key=lambda kv: -abs(kv[1]))[:5])
        evidence.append(Evidence(
            probe=self.name,
            kind="correlation_profile",
            summary=f"feature/target correlations (strongest first): {ranked}",
            data={"correlations": correlations},
            confidence="high",
        ))
        return evidence
