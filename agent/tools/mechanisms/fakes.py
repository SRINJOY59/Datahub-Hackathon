"""Canned Mechanisms implementation (a stand-in tool bundle).

Lets the agent run end-to-end before the real DataHub / MLflow / dbt / GitHub
tools exist. Mirrors the fraud scenario: a poisoned avg_txn_amount feature that
trips an assertion and drifts the model. Real tools will live beside this in
agent/tools/ and the agent won't change.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agent.contracts import (
    ActionRecord,
    ActionType,
    ContextBundle,
    Incident,
    LineageNode,
    Mechanisms,
    PostMortem,
    SignalType,
    ValidationResult,
    is_protective,
)

FEATURE_URN = "urn:li:dataset:(urn:li:dataPlatform:dbt,fraud_demo.fraud.main.feat_user_txn_stats,PROD)"


class FakeMechanisms(Mechanisms):
    def __init__(self) -> None:
        self._healthy = False  # flips to True after a successful fix
        self._applied: list[ActionRecord] = []

    def detect_incidents(self) -> list[Incident]:
        if self._healthy:
            return []
        return [
            Incident(
                id="INC-001",
                asset_urn=FEATURE_URN,
                signal_type=SignalType.ASSERTION_FAILURE,
                detected_at=datetime.now(timezone.utc),
                summary="assert_avg_txn_amount_plausible failed (2 users > 10000)",
                raw_evidence={"failing_rows": 2, "max_avg": 125471.0},
            )
        ]

    def read_context(self, asset_urn: str) -> ContextBundle:
        return ContextBundle(
            asset_urn=asset_urn,
            name="feat_user_txn_stats",
            entity_type="dataset",
            upstream=[
                LineageNode(
                    "urn:li:dataset:(urn:li:dataPlatform:dbt,fraud_demo.fraud.main.stg_transactions,PROD)",
                    "stg_transactions", "dataset"),
                LineageNode(
                    "urn:li:dataset:(urn:li:dataPlatform:dbt,fraud_demo.fraud.main.raw_transactions,PROD)",
                    "raw_transactions", "dataset"),
            ],
            downstream=[
                LineageNode(
                    "urn:li:dataset:(urn:li:dataPlatform:dbt,fraud_demo.fraud.main.training_dataset,PROD)",
                    "training_dataset", "dataset"),
                LineageNode(
                    "urn:li:mlModel:(urn:li:dataPlatform:mlflow,fraud_detection_model_1,PROD)",
                    "fraud_detection_model_1", "mlModel"),
                LineageNode(
                    "urn:li:mlModelDeployment:(urn:li:dataPlatform:mlflow,fraud_scoring_api,PROD)",
                    "fraud_scoring_api", "mlModelDeployment"),
            ],
            schema_fields=["user_id", "user_txn_count", "avg_txn_amount",
                           "stddev_txn_amount", "max_txn_amount"],
            owners=["jordan.rivera"],
            tags=["Tier-Critical", "PII"],
            failed_assertions=["assert_avg_txn_amount_plausible"],
        )

    def run_checks(self, asset_urn: str) -> ValidationResult:
        if self._healthy:
            return ValidationResult(passed=True, checks_run=["assert_avg_txn_amount_plausible"])
        return ValidationResult(
            passed=False,
            checks_run=["assert_avg_txn_amount_plausible"],
            failures=["assert_avg_txn_amount_plausible"],
        )

    def act(self, action: ActionRecord) -> ActionRecord:
        action.applied_at = datetime.now(timezone.utc)
        action.status = "applied"
        action.inverse = ActionRecord(
            action_type=action.action_type,
            target=action.target,
            params={"restore": True, **action.params},
            note=f"inverse of {action.action_type.value}",
        )
        if action.action_type in (ActionType.REPOINT_MODEL, ActionType.PIN_FEATURE):
            self._healthy = True
        self._applied.append(action)
        return action

    def undo(self, action: ActionRecord) -> bool:
        if action.action_type in (ActionType.REPOINT_MODEL, ActionType.PIN_FEATURE):
            self._healthy = False
        action.status = "reverted"
        return True

    def rollback(self, incident_id: str,
                 mutating_only: bool = False) -> tuple[int, int]:
        """Mirror the real journal's contract: unwind in reverse order, optionally
        leaving protective actions in place."""
        return self._undo_where(
            lambda a: not (mutating_only and is_protective(a.action_type)))

    def release_containment(self, incident_id: str) -> tuple[int, int]:
        """Lift only the protective actions, once the incident is fixed."""
        return self._undo_where(lambda a: is_protective(a.action_type))

    def _undo_where(self, keep) -> tuple[int, int]:
        reverted = 0
        for action in reversed([a for a in self._applied if a.status == "applied"]):
            if keep(action) and self.undo(action):
                reverted += 1
        return reverted, 0

    def propose_fix(self, incident: Incident, context: ContextBundle,
                    root_cause: str) -> str:
        return "https://github.com/your-org/fraud-pipeline/pull/42"

    def write_back(self, post_mortem: PostMortem, resolved: bool = True) -> None:
        state = "resolved" if resolved else "contained"
        print(f"    [fake write_back] {state} post-mortem for "
              f"{post_mortem.incident_id} -> DataHub "
              f"({len(post_mortem.blast_radius)} affected assets)")
