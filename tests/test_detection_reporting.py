"""Drift maths, contract parity, reporting, and the pieces of the shadow and
runbook machinery that need nothing running.
"""
from __future__ import annotations

import pytest

from agent.contracts import ActionRecord, ActionType, ChangeType, SignalType
from ml.drift import compute_drift, relative_shift


def snapshot(rate=0.10, score=0.20, **means):
    return {"positive_pred_rate": rate, "mean_score": score,
            "feature_means": means or {"amount": 50.0, "avg_txn_amount": 60.0}}


class TestDrift:
    def test_identical_runs_have_not_drifted(self):
        base = snapshot()
        assert compute_drift(dict(base), base).drifted is False

    def test_prediction_rate_shift(self):
        report = compute_drift(snapshot(rate=0.16), snapshot())
        assert report.drifted
        assert report.reasons == ["prediction-rate shift"]

    def test_feature_shift_names_the_worst_one(self):
        report = compute_drift(snapshot(amount=100.0, avg_txn_amount=61.0),
                               snapshot())
        assert report.drifted
        assert report.worst_feature == "amount"
        assert report.worst_feature_delta == pytest.approx(1.0)

    def test_a_missing_reference_is_not_a_drift_claim(self):
        assert compute_drift({}, {}).drifted is False
        assert compute_drift(snapshot(), {}).drifted is False

    def test_features_absent_from_the_baseline_are_ignored(self):
        report = compute_drift(snapshot(amount=50.0, brand_new=999.0), snapshot())
        assert "brand_new" not in report.feature_drift

    def test_relative_shift_survives_a_zero_reference(self):
        assert relative_shift(5.0, 0.0) == 0.0
        assert relative_shift(60.0, 50.0) == pytest.approx(0.2)


class TestContractParity:
    def test_the_llm_can_name_every_change_type(self):
        """A hand-written subset here once forced the model into a wrong value
        for every class it omitted."""
        from agent.schemas import RCAResult

        exposed = RCAResult.model_json_schema()["$defs"]["ChangeType"]["enum"]
        assert set(exposed) == {c.value for c in ChangeType}

    def test_every_new_signal_maps_to_a_change_type(self):
        """Anything unmapped falls through to `unknown` and gets the do-nothing
        recipe, which is how a detected incident goes unremediated."""
        from agent.rca import SIGNAL_TO_CHANGE

        deliberately_open = {SignalType.ASSERTION_FAILURE, SignalType.SCHEMA_CHANGE}
        unmapped = {s for s in SignalType if s not in SIGNAL_TO_CHANGE}
        assert unmapped == deliberately_open

    def test_every_action_type_has_an_actuator(self):
        import agent.tools.actuators  # noqa: F401
        from agent.registry import build_actuators

        registered = set(build_actuators())
        assert set(ActionType) - registered == set()


class TestSavingsDigest:
    def _digest(self, tmp_path, entries):
        from agent.journal import ActionJournal
        from agent.reporting.digest import SavingsDigest

        journal = ActionJournal(tmp_path / "j.jsonl")
        for action_type, incident, simulated in entries:
            record = ActionRecord(action_type, "urn:x")
            if simulated:
                journal.record_simulated(record, incident)
            else:
                journal.record_applied(record, incident)
        return SavingsDigest(journal).build()

    def test_counts_incidents_not_actions(self, tmp_path):
        digest = self._digest(tmp_path, [
            (ActionType.PIN_FEATURE, "INC-1", False),
            (ActionType.TAG_ASSET, "INC-1", False),
            (ActionType.REPOINT_MODEL, "INC-2", False),
        ])
        assert digest.incidents == 2
        assert digest.actions_applied == 3
        assert digest.by_action == {"pin_feature": 1, "tag_asset": 1,
                                    "repoint_model": 1}

    def test_shadow_mode_is_reported_as_hypothetical(self, tmp_path):
        digest = self._digest(tmp_path, [(ActionType.PIN_FEATURE, "INC-1", True)])
        assert digest.shadow_mode
        assert digest.actions_applied == 0
        assert "would have" in digest.render()

    def test_a_failed_action_saved_nobody_any_time(self, tmp_path):
        from agent.journal import ActionJournal
        from agent.reporting.digest import SavingsDigest

        journal = ActionJournal(tmp_path / "j.jsonl")
        journal.record_failed(ActionRecord(ActionType.PIN_FEATURE, "x"), "INC-1", "boom")
        digest = SavingsDigest(journal).build()
        assert digest.actions_failed == 1
        assert digest.hours_saved == 0.0

    def test_an_empty_journal_claims_nothing(self, tmp_path):
        digest = self._digest(tmp_path, [])
        assert (digest.incidents, digest.hours_saved) == (0, 0.0)

    def test_the_estimate_is_labelled_as_one(self, tmp_path):
        """The hours are the weakest number here, so the output has to say so."""
        rendered = self._digest(tmp_path,
                                [(ActionType.PIN_FEATURE, "INC-1", False)]).render()
        assert "not a measurement" in rendered


class TestTrustScoring:
    def test_a_healthy_asset_scores_full_marks(self):
        from agent.tools.graph.trust import HealthSignals, score_from_signals

        assert score_from_signals(HealthSignals()) == 100.0

    def test_a_failing_assertion_drops_the_grade(self):
        """A broken pipeline showing grade A is the reassurance nobody should
        be given — this was a real bug."""
        from agent.tools.graph.trust import (HealthSignals, _grade,
                                             score_from_signals)

        value = score_from_signals(HealthSignals(failed_assertions=1))
        assert value == 75.0
        assert _grade(value) == "B"

    def test_history_cannot_sink_an_otherwise_healthy_asset(self):
        from agent.tools.graph.trust import HealthSignals, score_from_signals

        assert score_from_signals(HealthSignals(past_incidents=50)) == 80.0

    def test_the_score_has_a_floor(self):
        from agent.tools.graph.trust import HealthSignals, score_from_signals

        assert score_from_signals(
            HealthSignals(9, True, -0.9, 500, 99)) == 0.0

    @pytest.mark.parametrize("value,grade", [
        (100, "A"), (90, "A"), (89.9, "B"), (70, "B"), (69.9, "C"),
        (50, "C"), (49.9, "D"), (0, "D"),
    ])
    def test_grade_boundaries(self, value, grade):
        from agent.tools.graph.trust import _grade

        assert _grade(value) == grade


class TestShadowVerification:
    def test_valid_python_passes_and_says_what_it_proved(self):
        from agent.tools.warehouse.shadow import ShadowEnvironment

        result = ShadowEnvironment.verify_python("c.py", "FEATURES = ['a']\n")
        assert result.passed
        assert "behaviour not" in result.note

    def test_a_confidently_broken_fix_is_rejected(self):
        from agent.tools.warehouse.shadow import ShadowEnvironment

        result = ShadowEnvironment.verify_python("c.py", "FEATURES = ['a'\n")
        assert not result.passed
        assert result.failures


class TestRunbook:
    def test_instructions_carry_every_section(self):
        from agent.schemas import Runbook

        text = Runbook(
            title="Handle a null spike", summary="Upstream stopped sending values.",
            symptoms=["not_null fails"], diagnosis_steps=["profile the column"],
            mitigation_steps=["quarantine, then pin"],
            verification_steps=["re-run the assertions"],
            required_tools=["duckdb"],
        ).as_instructions()

        for heading in ("Symptoms", "Diagnosis", "Mitigation", "Verification",
                        "Requires"):
            assert f"## {heading}" in text
        assert text.startswith("# Handle a null spike")

    def test_tools_are_folded_into_the_text(self):
        """DataHub's requiredTools field holds urns and rejects prose, so the
        tool list has to live somewhere a human will actually read it."""
        from agent.schemas import Runbook

        text = Runbook(title="t", summary="s", symptoms=[], diagnosis_steps=[],
                       mitigation_steps=[], verification_steps=[],
                       required_tools=["SQL access to raw_transactions"]).as_instructions()
        assert "SQL access to raw_transactions" in text

    def test_empty_sections_are_omitted_rather_than_left_blank(self):
        from agent.schemas import Runbook

        text = Runbook(title="t", summary="s", symptoms=["only this"],
                       diagnosis_steps=[], mitigation_steps=[],
                       verification_steps=[]).as_instructions()
        assert "## Symptoms" in text
        assert "## Diagnosis" not in text


class TestAssertionNames:
    @pytest.mark.parametrize("unique_id,expected", [
        ("test.fraud_pipeline.assert_avg_txn_amount_plausible",
         "assert_avg_txn_amount_plausible"),
        ("test.fraud_pipeline.not_null_stg_transactions_amount.cd2030fcf6",
         "not_null_stg_transactions_amount"),
        ("model.fraud_pipeline.training_dataset", "training_dataset"),
        ("", ""),
    ])
    def test_the_uniqueness_hash_is_stripped(self, unique_id, expected):
        """An incident reading `1 failed assertion: a321883ce7` tells the on-call
        nothing about what broke."""
        from agent.tools.warehouse.dbt_runner import _readable

        assert _readable(unique_id) == expected
