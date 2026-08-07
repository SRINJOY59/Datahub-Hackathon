"""Tests for bugs that were found by running the thing, not by reading it.

Each of these was invisible to review and to the rest of the suite. They are kept
apart from the behavioural tests because the point of each is a specific past
failure, and the comment explaining what broke is as much the test as the
assertion is.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestAssertionsAreAttachedToTheirModel:
    """A dbt test written with a bare table name compiles, runs, and fails
    correctly — and is invisible to the agent.

    The agent finds incidents by walking datasets and asking DataHub for each
    one's failing assertions. A test with no recorded dependency belongs to no
    dataset, so it can never be returned. `assert_amount_distribution_stable` was
    written that way, which meant the distribution trip-wire — the check that
    exists specifically to catch subtle drift — never raised an incident.
    `distribution_drift` looked like it worked only because a different assertion
    happened to fail at the same time.
    """

    SINGULAR_TESTS = sorted((REPO_ROOT / "pipeline" / "dbt" / "tests").glob("*.sql"))

    def test_there_are_singular_tests_to_check(self):
        assert self.SINGULAR_TESTS, "no singular dbt tests found"

    @pytest.mark.parametrize("sql_path", SINGULAR_TESTS, ids=lambda p: p.stem)
    def test_every_singular_test_uses_ref(self, sql_path):
        body = sql_path.read_text(encoding="utf-8")
        assert "ref(" in body, (
            f"{sql_path.name} refers to its model by bare table name. dbt will "
            f"record no dependency, DataHub will attach the assertion to no "
            f"dataset, and the agent will never see it fail."
        )

    def test_the_manifest_agrees(self):
        """The real check, when a manifest is available: dbt itself must report a
        dependency for every assertion."""
        manifest = REPO_ROOT / "pipeline" / "dbt" / "target" / "manifest.json"
        if not manifest.exists():
            pytest.skip("no dbt manifest — run `dbt compile` first")

        nodes = json.loads(manifest.read_text(encoding="utf-8"))["nodes"]
        orphaned = [
            uid.split(".")[-1] for uid, node in nodes.items()
            if node["resource_type"] == "test"
            and not node["depends_on"]["nodes"]
        ]
        assert orphaned == [], (
            f"these assertions are attached to no dataset, so the agent cannot "
            f"see them fail: {orphaned}"
        )


class TestMeasuredClassificationsAreHighConfidence:
    """Confidence drove the autonomy tier, and the LLM drove confidence.

    A volume collapse is 3218 rows against a baseline of 8000. That is
    arithmetic, not a judgement — but the narrative model was allowed to call it
    "medium", which dropped a PII asset to HUMAN_ONLY and withheld the repair.
    The same scenario therefore repaired itself on one run and merely contained
    itself on the next, with nothing about the incident having changed.

    Confidence now belongs to whatever produced the classification: measured
    means high, and the model only sets it when it also did the classifying.
    """

    def _rca(self, monkeypatch, signal, evidence, llm_confidence=None):
        from datetime import datetime, timezone

        from agent.contracts import Evidence, Incident, ContextBundle
        from agent.rca import RCAEngine
        from agent.schemas import RCAResult

        engine = RCAEngine.__new__(RCAEngine)   # skip DataHub in __init__
        engine.probes = []
        engine.lineage = None
        engine.memory = None
        engine.llm = None

        monkeypatch.setattr(engine, "_synthesize", lambda *a, **k: (
            RCAResult(root_cause="narrative", change_type="unknown",
                      confidence=llm_confidence,
                      recommended_mitigation="do something")
            if llm_confidence else None))
        monkeypatch.setattr(RCAEngine, "_pick_root",
                            staticmethod(lambda ev: evidence))

        urn = "urn:li:dataset:(urn:li:dataPlatform:dbt,f.f.main.raw_transactions,PROD)"
        incident = Incident("INC-1", urn, signal, datetime.now(timezone.utc), "s")
        return engine.analyze(incident, ContextBundle(asset_urn=urn, name="t",
                                                      entity_type="dataset"))

    def test_a_signal_that_names_the_change_is_high_confidence(self, monkeypatch):
        """volume_anomaly, freshness and the rest are measurements. The model
        must not be able to talk the tier down from them."""
        from agent.contracts import SignalType

        for signal in (SignalType.VOLUME_ANOMALY, SignalType.FRESHNESS,
                       SignalType.MODEL_DRIFT, SignalType.LABEL_LEAKAGE,
                       SignalType.TRAINING_SERVING_SKEW):
            rca = self._rca(monkeypatch, signal, evidence=None,
                            llm_confidence="medium")
            assert rca.confidence == "high", signal.value

    def test_a_profiled_column_is_high_confidence(self, monkeypatch):
        from agent.contracts import Evidence, SignalType

        root = Evidence(probe="data_profile", kind="scale_shift", summary="s",
                        data={"column": "amount", "table": "raw_transactions",
                              "change_type": "scale_shift", "depth": 2})
        rca = self._rca(monkeypatch, SignalType.ASSERTION_FAILURE, evidence=root,
                        llm_confidence="low")
        assert rca.confidence == "high"
        assert rca.change_type.value == "scale_shift"

    def test_the_model_still_decides_when_it_did_the_classifying(self, monkeypatch):
        """Nothing measured anything here, so the confidence is genuinely the
        model's to give."""
        from agent.contracts import SignalType

        rca = self._rca(monkeypatch, SignalType.ASSERTION_FAILURE, evidence=None,
                        llm_confidence="medium")
        assert rca.confidence == "medium"

    def test_no_evidence_and_no_model_is_low_confidence(self, monkeypatch):
        from agent.contracts import SignalType

        rca = self._rca(monkeypatch, SignalType.ASSERTION_FAILURE, evidence=None)
        assert rca.confidence == "low"

    def test_confidence_decides_whether_a_pii_asset_gets_repaired(self):
        """The link that made this matter: on a PII asset, anything below high
        withholds every data change."""
        from agent.contracts import AutonomyTier, ChangeType, ContextBundle, RootCauseAnalysis
        from agent.policy import AutonomyPolicy

        context = ContextBundle(asset_urn="urn:x", name="raw_transactions",
                                entity_type="dataset", tags=["PII"])

        def tier(confidence):
            return AutonomyPolicy().tier(context, RootCauseAnalysis(
                incident_id="i", root_cause_asset="urn:x", root_cause_column=None,
                change_type=ChangeType.VOLUME_ANOMALY, confidence=confidence,
                narrative="n"))

        assert tier("high") is AutonomyTier.PR_ONLY       # repairs allowed
        assert tier("medium") is AutonomyTier.HUMAN_ONLY  # repairs withheld


class TestResetRestoresEveryReference:
    """A reset that misses one reference lets a scenario poison later runs.

    `training_serving_skew` advances the scoring baseline on purpose — that is
    how it isolates skew from drift. Reset restored the warehouse, the snapshots,
    the volume/freshness baseline, the champion alias and the breakers, but not
    that baseline, so the shifted reference survived. Every subsequent
    `model_drift` run then compared a 1.4x shift against an already-1.6x
    reference, read -12%, and detected nothing. The scenario looked broken; the
    reset was.
    """

    def test_reset_re_anchors_every_known_good_reference(self):
        import inspect

        from scenarios.base import PipelineReset

        source = inspect.getsource(PipelineReset._capture_last_good)
        for reference, what in [
            ("SnapshotStore", "table snapshots the Time Machine restores from"),
            ("BaselineStore", "volume/freshness baseline"),
            ("rescore", "scoring baseline the drift detector compares against"),
        ]:
            assert reference in source, (
                f"reset does not re-anchor the {what}; a scenario that moves it "
                f"will silently change what later runs detect"
            )

    def test_a_stale_baseline_hides_a_real_drift(self):
        """The arithmetic behind the bug, so the threshold interaction is
        explicit rather than folklore."""
        from ml.drift import FEATURE_DRIFT_THRESHOLD, compute_drift

        clean, drifted = 60.41, 60.41 * 1.4          # what model_drift injects
        skewed_baseline = 60.41 * 1.6                # what the skew scenario left

        def report(baseline_mean):
            return compute_drift(
                {"positive_pred_rate": 0.01, "mean_score": 0.03,
                 "feature_means": {"amount": drifted}},
                {"positive_pred_rate": 0.01, "mean_score": 0.03,
                 "feature_means": {"amount": baseline_mean}})

        against_clean = report(clean)
        assert against_clean.drifted
        assert abs(against_clean.worst_feature_delta) >= FEATURE_DRIFT_THRESHOLD

        against_stale = report(skewed_baseline)
        assert not against_stale.drifted, (
            "a stale baseline must not be able to hide a real drift — this is the "
            "failure the reset fix prevents"
        )


class TestTrustScorerReportsFailingAssertions:
    """TrustScorer never stored gms_server, so the lookup that reads an asset's
    failing assertions raised AttributeError straight into a broad `except` and
    every asset scored as though its tests passed. A visibly broken pipeline was
    being published to the catalog with a grade of A.
    """

    def test_the_scorer_keeps_what_it_needs_to_ask(self):
        import inspect

        from agent.tools.graph.trust import TrustScorer

        source = inspect.getsource(TrustScorer.__init__)
        assert "self.gms_server" in source, (
            "TrustScorer must retain gms_server; without it the failing-assertion "
            "lookup raises into a swallowing except and every asset scores as healthy"
        )

    def test_a_failing_assertion_actually_moves_the_grade(self):
        from agent.tools.graph.trust import HealthSignals, _grade, score_from_signals

        healthy = score_from_signals(HealthSignals())
        broken = score_from_signals(HealthSignals(failed_assertions=1))
        assert broken < healthy
        assert _grade(broken) != "A"
