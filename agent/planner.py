"""Choosing what to do about an incident.

The mitigation follows from the diagnosis, so the plan is a table indexed by
ChangeType rather than a chain of conditionals — which is also what makes it
reviewable: someone can read what the agent will do about a null spike without
reading any code that does it.

Two rules shape the table:

  * fix upstream, not where it hurt. The RCA names the table the change actually
    originated in, and that is what gets repaired; repairing the feature table
    that tripped the assertion would be undone by the next rebuild.
  * absence is not corruption. When a feed goes stale or the data simply is not
    there, rolling back to a snapshot would invent data that never arrived. Those
    incidents get protective actions only, and a human is told.
"""
from __future__ import annotations

from agent.contracts import (
    ActionRecord,
    ActionType,
    AutonomyTier,
    ChangeType,
    ContextBundle,
    RootCauseAnalysis,
)
from agent.policy import AutonomyPolicy
from agent.tools.graph.urns import table_of

SCORING_JOB = "fraud_scoring_api"

# ChangeType -> the ordered mitigation recipe.
RECIPES: dict[ChangeType, list[ActionType]] = {
    ChangeType.NULL_SPIKE:        [ActionType.QUARANTINE, ActionType.PIN_FEATURE,
                                   ActionType.TAG_ASSET],
    ChangeType.SCALE_SHIFT:       [ActionType.QUARANTINE, ActionType.PIN_FEATURE,
                                   ActionType.TAG_ASSET],
    ChangeType.RANGE_VIOLATION:   [ActionType.QUARANTINE, ActionType.PIN_FEATURE,
                                   ActionType.TAG_ASSET],
    ChangeType.SCHEMA_CHANGE:     [ActionType.PIN_FEATURE, ActionType.TAG_ASSET],
    ChangeType.DISTRIBUTION_DRIFT: [ActionType.TAG_ASSET, ActionType.REPOINT_MODEL],
    ChangeType.MODEL_DRIFT:       [ActionType.TAG_ASSET, ActionType.REPOINT_MODEL],
    ChangeType.VOLUME_ANOMALY:    [ActionType.PIN_FEATURE, ActionType.TAG_ASSET],
    ChangeType.DUPLICATE_RECORDS: [ActionType.DEDUPE_PARTITION, ActionType.TAG_ASSET],
    ChangeType.FRESHNESS_LAG:     [ActionType.TAG_ASSET, ActionType.PAUSE_JOB],
    ChangeType.TRAINING_SERVING_SKEW: [ActionType.TAG_ASSET, ActionType.PAUSE_JOB],
    ChangeType.TRAINING_REGRESSION: [ActionType.REPOINT_MODEL],
    ChangeType.LABEL_LEAKAGE:     [ActionType.PAUSE_JOB, ActionType.REPOINT_MODEL],
    # Code and dependency breaks are fixed by a pull request, not by moving data.
    ChangeType.DEPENDENCY_CHANGE: [],
    ChangeType.CODE_CHANGE:       [],
    ChangeType.UNKNOWN:           [ActionType.TAG_ASSET],
}


class RemediationPlanner:
    """Turns a diagnosis into an ordered list of reversible actions."""

    def __init__(self, policy: AutonomyPolicy | None = None) -> None:
        self.policy = policy or AutonomyPolicy()

    def plan(self, rca: RootCauseAnalysis, context: ContextBundle,
             tier: AutonomyTier) -> tuple[list[ActionRecord], list[ActionRecord]]:
        """Returns (actions to run now, actions withheld by the autonomy tier)."""
        recipe = RECIPES.get(rca.change_type, RECIPES[ChangeType.UNKNOWN])
        actions = [a for step in recipe
                   for a in self._build(step, rca, context)]
        return self.policy.filter(tier, actions)

    # ------------------------------------------------------------------ #
    def _build(self, step: ActionType, rca: RootCauseAnalysis,
               context: ContextBundle) -> list[ActionRecord]:
        root_table = table_of(rca.root_cause_asset) or table_of(context.asset_urn)

        if step is ActionType.TAG_ASSET:
            # Warn the consumers, not the asset itself — they are the ones who
            # would otherwise keep using bad data without knowing.
            return [
                ActionRecord(ActionType.TAG_ASSET, node.urn,
                             incident_id=rca.incident_id,
                             note=f"downstream of {root_table}")
                for node in context.downstream
            ]

        if step is ActionType.PAUSE_JOB:
            return [ActionRecord(
                ActionType.PAUSE_JOB, SCORING_JOB,
                params={"job": SCORING_JOB,
                        "reason": f"{rca.change_type.value} on {root_table}"},
                incident_id=rca.incident_id,
                note="stop serving on data we believe is bad",
            )]

        if step is ActionType.REPOINT_MODEL:
            return [ActionRecord(
                ActionType.REPOINT_MODEL, SCORING_JOB,
                incident_id=rca.incident_id,
                note="roll the champion back to the last validated version",
            )]

        if step is ActionType.QUARANTINE:
            if not (root_table and rca.root_cause_column):
                return []  # nothing precise enough to isolate
            return [ActionRecord(
                ActionType.QUARANTINE, rca.root_cause_asset,
                params={"table": root_table, "column": rca.root_cause_column,
                        "change_type": rca.change_type.value},
                incident_id=rca.incident_id,
                note=f"isolate bad rows in {root_table}.{rca.root_cause_column}",
            )]

        if step is ActionType.PIN_FEATURE:
            if not root_table:
                return []
            return [ActionRecord(
                ActionType.PIN_FEATURE, rca.root_cause_asset or context.asset_urn,
                params={"table": root_table},
                incident_id=rca.incident_id,
                note=f"restore {root_table} to its last known-good contents",
            )]

        if step is ActionType.DEDUPE_PARTITION:
            if not root_table:
                return []
            return [ActionRecord(
                ActionType.DEDUPE_PARTITION,
                rca.root_cause_asset or context.asset_urn,
                params={"table": root_table},
                incident_id=rca.incident_id,
                note=f"remove duplicate keys from {root_table}",
            )]

        return []
