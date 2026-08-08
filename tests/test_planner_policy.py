"""What the agent decides to do, and how much of it it is allowed to do.

The planner is a lookup table on purpose, so these read as a specification of the
agent's behaviour rather than as tests of an algorithm.
"""
from __future__ import annotations

import pytest

from agent.contracts import (
    ActionRecord,
    ActionType,
    AutonomyTier,
    ChangeType,
    ContextBundle,
    LineageNode,
    RootCauseAnalysis,
)
from agent.planner import RECIPES, RemediationPlanner
from agent.policy import AutonomyPolicy

DATASET = "urn:li:dataset:(urn:li:dataPlatform:dbt,f.f.main.feat_user_txn_stats,PROD)"
SOURCE = "urn:li:dataset:(urn:li:dataPlatform:dbt,f.f.main.raw_transactions,PROD)"


def context(tags=(), downstream=2):
    return ContextBundle(
        asset_urn=DATASET, name="feat_user_txn_stats", entity_type="dataset",
        downstream=[LineageNode(f"urn:li:dataset:(urn:li:dataPlatform:dbt,f.f.main.d{i},PROD)",
                                f"d{i}", "dataset") for i in range(downstream)],
        owners=["jordan"], tags=list(tags))


def rca(change_type, confidence="high", column="amount"):
    return RootCauseAnalysis(
        incident_id="INC-1", root_cause_asset=SOURCE, root_cause_column=column,
        change_type=change_type, confidence=confidence, narrative="n")


def kinds(actions):
    seen = []
    for a in actions:
        if not seen or seen[-1] != a.action_type.value:
            seen.append(a.action_type.value)
    return seen


class TestRecipes:
    def test_every_change_type_has_a_recipe(self):
        """A missing entry silently becomes the do-nothing fallback, which is how
        five incident classes would have gone unremediated."""
        missing = [c.value for c in ChangeType if c not in RECIPES]
        assert missing == []

    @pytest.mark.parametrize("change_type,expected", [
        (ChangeType.NULL_SPIKE, ["quarantine", "pin_feature", "tag_asset"]),
        (ChangeType.SCALE_SHIFT, ["quarantine", "pin_feature", "tag_asset"]),
        (ChangeType.SCHEMA_CHANGE, ["pin_feature", "tag_asset"]),
        (ChangeType.VOLUME_ANOMALY, ["pin_feature", "tag_asset"]),
        (ChangeType.DUPLICATE_RECORDS, ["dedupe_partition", "tag_asset"]),
        (ChangeType.MODEL_DRIFT, ["tag_asset", "repoint_model"]),
        (ChangeType.FRESHNESS_LAG, ["tag_asset", "pause_job"]),
        (ChangeType.TRAINING_SERVING_SKEW, ["tag_asset", "pause_job"]),
        (ChangeType.LABEL_LEAKAGE, ["pause_job", "tag_asset"]),
        (ChangeType.TRAINING_REGRESSION, ["repoint_model"]),
    ])
    def test_plan_for(self, change_type, expected):
        actions, _ = RemediationPlanner().plan(rca(change_type), context(),
                                               AutonomyTier.AUTO)
        assert kinds(actions) == expected

    def test_code_changes_are_fixed_by_a_pull_request_not_a_data_action(self):
        for change_type in (ChangeType.DEPENDENCY_CHANGE, ChangeType.CODE_CHANGE):
            actions, _ = RemediationPlanner().plan(rca(change_type), context(),
                                                   AutonomyTier.AUTO)
            assert actions == []

    def test_absence_is_never_repaired_by_rolling_back(self):
        """A stale feed has no rows to restore, so pinning would invent data that
        never arrived."""
        for change_type in (ChangeType.FRESHNESS_LAG,
                            ChangeType.TRAINING_SERVING_SKEW):
            assert ActionType.PIN_FEATURE not in RECIPES[change_type]
            assert ActionType.QUARANTINE not in RECIPES[change_type]

    def test_leakage_does_not_attempt_a_repair_it_cannot_finish(self):
        """Repointing away from a leaked champion looks helpful and is not: every
        earlier version was fitted to a distribution the leaked feature no longer
        matches, so the gate stays red and the rollback restores the leaked model.
        The attempt achieved nothing and undid itself."""
        assert ActionType.REPOINT_MODEL not in RECIPES[ChangeType.LABEL_LEAKAGE]

    def test_containment_only_recipes_are_recognised_as_such(self):
        """These reach the contained outcome rather than the rolled-back one,
        which is what keeps the breaker closed and the warnings up."""
        policy = AutonomyPolicy()
        for change_type in (ChangeType.FRESHNESS_LAG,
                            ChangeType.TRAINING_SERVING_SKEW,
                            ChangeType.LABEL_LEAKAGE):
            actions, _ = RemediationPlanner(policy).plan(
                rca(change_type), context(), AutonomyTier.AUTO)
            assert policy.is_containment_only(actions), change_type.value

    def test_repair_targets_the_root_table_not_the_one_that_complained(self):
        """Repairing the feature table would be undone by the next rebuild."""
        actions, _ = RemediationPlanner().plan(rca(ChangeType.SCALE_SHIFT),
                                               context(), AutonomyTier.AUTO)
        pin = next(a for a in actions if a.action_type is ActionType.PIN_FEATURE)
        assert pin.params["table"] == "raw_transactions"

    def test_quarantine_needs_a_column_to_isolate_on(self):
        actions, _ = RemediationPlanner().plan(
            rca(ChangeType.SCALE_SHIFT, column=None), context(), AutonomyTier.AUTO)
        assert ActionType.QUARANTINE not in [a.action_type for a in actions]

    def test_every_downstream_consumer_is_warned(self):
        actions, _ = RemediationPlanner().plan(rca(ChangeType.SCALE_SHIFT),
                                               context(downstream=5),
                                               AutonomyTier.AUTO)
        tags = [a for a in actions if a.action_type is ActionType.TAG_ASSET]
        assert len(tags) == 5


class TestAutonomyPolicy:
    @pytest.mark.parametrize("tags,confidence,downstream,expected", [
        ([], "high", 2, AutonomyTier.AUTO),
        (["PII"], "high", 2, AutonomyTier.PR_ONLY),
        (["PII"], "medium", 2, AutonomyTier.HUMAN_ONLY),
        (["PII"], "low", 2, AutonomyTier.HUMAN_ONLY),
        (["Tier-Critical"], "high", 2, AutonomyTier.PR_ONLY),
        ([], "low", 2, AutonomyTier.PR_ONLY),
        ([], "high", 9, AutonomyTier.PR_ONLY),
    ])
    def test_tier(self, tags, confidence, downstream, expected):
        tier = AutonomyPolicy().tier(context(tags, downstream),
                                     rca(ChangeType.SCALE_SHIFT, confidence))
        assert tier is expected

    def test_human_only_withholds_data_changes_but_still_protects(self):
        """Withholding the protective actions while waiting for a human would be
        the riskier choice — they only ever reduce harm."""
        policy = AutonomyPolicy()
        actions, withheld = RemediationPlanner(policy).plan(
            rca(ChangeType.SCALE_SHIFT), context(["PII"]), AutonomyTier.HUMAN_ONLY)
        assert kinds(actions) == ["tag_asset"]
        assert set(kinds(withheld)) == {"quarantine", "pin_feature"}

    def test_lower_tiers_withhold_nothing(self):
        for tier in (AutonomyTier.AUTO, AutonomyTier.PR_ONLY):
            _, withheld = RemediationPlanner().plan(rca(ChangeType.SCALE_SHIFT),
                                                    context(), tier)
            assert withheld == []

    def test_containment_only_means_nothing_here_could_have_repaired_it(self):
        policy = AutonomyPolicy()
        protective = [ActionRecord(ActionType.TAG_ASSET, "x"),
                      ActionRecord(ActionType.PAUSE_JOB, "y")]
        assert policy.is_containment_only(protective)
        assert not policy.is_containment_only(
            protective + [ActionRecord(ActionType.PIN_FEATURE, "z")])
        assert not policy.is_containment_only([])
