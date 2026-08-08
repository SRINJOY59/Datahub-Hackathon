"""The deterministic classifiers — what the agent decides before any LLM runs.

These matter more than most of the code they support: the LLM narrates whatever
these conclude, so a wrong classification here becomes a confident, well-written
wrong explanation downstream.
"""
from __future__ import annotations

from agent.contracts import ChangeType, ColumnProfile
from agent.tools.warehouse.profiler import classify, identify_leaks


def profile(**kw) -> ColumnProfile:
    base = dict(dataset_urn="", table="raw_transactions", column="amount")
    base.update(kw)
    return ColumnProfile(**base)


class TestClassify:
    def test_missing_column_is_a_schema_change(self):
        change, note = classify(profile(exists=False))
        assert change is ChangeType.SCHEMA_CHANGE
        assert "missing" in note

    def test_column_present_but_entirely_empty_is_a_schema_change(self):
        """A rename in disguise: the column still exists and is simply never
        populated, so neither the missing-column nor the null-spike branch fires.
        This was a real gap — schema_change resolved to `unknown` for months."""
        change, note = classify(profile(null_rate=1.0, recent_null_rate=1.0))
        assert change is ChangeType.SCHEMA_CHANGE
        assert "stopped populating" in note

    def test_null_spike_needs_a_healthy_history_to_spike_away_from(self):
        change, _ = classify(profile(null_rate=0.1, recent_null_rate=0.5))
        assert change is ChangeType.NULL_SPIKE

    def test_uniformly_null_column_is_not_a_spike(self):
        change, _ = classify(profile(null_rate=0.5, recent_null_rate=0.5,
                                     mean=10.0, recent_mean=10.0))
        assert change is not ChangeType.NULL_SPIKE

    def test_scale_shift(self):
        change, note = classify(profile(mean=60.0, recent_mean=6000.0))
        assert change is ChangeType.SCALE_SHIFT
        assert "100.0x" in note

    def test_distribution_drift_is_the_gentler_band(self):
        change, _ = classify(profile(mean=60.0, recent_mean=120.0))
        assert change is ChangeType.DISTRIBUTION_DRIFT

    def test_a_stable_column_is_not_an_anomaly(self):
        change, _ = classify(profile(mean=60.0, recent_mean=61.0))
        assert change is ChangeType.UNKNOWN

    def test_uniform_shift_is_invisible_here_by_design(self):
        """model_drift shifts every row equally, so recent-vs-overall is 1.0 and
        the profiler correctly sees nothing. That failure is caught by comparing
        predictions against a baseline, not by profiling the column."""
        change, _ = classify(profile(mean=84.0, recent_mean=84.0))
        assert change is ChangeType.UNKNOWN


class TestIdentifyLeaks:
    def test_the_real_leak_is_found(self):
        """Measured from an actual label_leakage run: 0.703, which an absolute
        0.9 threshold would have missed entirely."""
        leaks = identify_leaks({"amount": 0.7035, "avg_txn_amount": 0.1435,
                                "stddev_txn_amount": 0.1417})
        assert leaks == {"amount": 0.7035}

    def test_clean_data_produces_no_leak(self):
        """Measured from the healthy pipeline — the strongest honest correlation
        is 0.166."""
        assert identify_leaks({"amount": 0.1659, "merchant_fraud_rate": 0.1390,
                               "is_risky_category": 0.1128}) == {}

    def test_strong_but_undominant_features_are_not_leaks(self):
        """Several genuinely predictive features should not be flagged just for
        being predictive. Leakage looks like one feature standing far apart."""
        assert identify_leaks({"a": 0.62, "b": 0.55, "c": 0.40}) == {}

    def test_negative_correlation_leaks_too(self):
        leaks = identify_leaks({"a": -0.8, "b": 0.1})
        assert leaks == {"a": -0.8}

    def test_a_single_feature_cannot_be_judged(self):
        """Dominance is meaningless without something to dominate."""
        assert identify_leaks({"only": 0.99}) == {}

    def test_no_features_at_all(self):
        assert identify_leaks({}) == {}
