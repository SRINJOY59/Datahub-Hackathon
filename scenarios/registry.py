"""The one place that knows which scenarios exist.

Three consumers need this list — the CLI (`python -m scenarios`), the
verification harness, and the agent's fire-drill mechanism — so it does not live
in any of them.
"""
from __future__ import annotations

from scenarios.api_breaking_change import ApiBreakingChangeScenario
from scenarios.base import BaseScenario
from scenarios.distribution_drift import DistributionDriftScenario
from scenarios.duplicate_batch import DuplicateBatchScenario
from scenarios.label_leakage import LabelLeakageScenario
from scenarios.model_drift import ModelDriftScenario
from scenarios.null_spike import NullSpikeScenario
from scenarios.risky_commit import RiskyCommitScenario
from scenarios.schema_change import SchemaChangeScenario
from scenarios.stale_feed import StaleFeedScenario
from scenarios.training_regression import TrainingRegressionScenario
from scenarios.training_serving_skew import TrainingServingSkewScenario
from scenarios.unit_bug import UnitBugScenario
from scenarios.volume_collapse import VolumeCollapseScenario

_REGISTERED: list[type[BaseScenario]] = [
    # Loud: something upstream broke and an assertion caught it.
    UnitBugScenario,
    NullSpikeScenario,
    DistributionDriftScenario,
    SchemaChangeScenario,
    DuplicateBatchScenario,
    # Silent: the pipeline is wrong and every assertion passes.
    StaleFeedScenario,
    VolumeCollapseScenario,
    ModelDriftScenario,
    TrainingServingSkewScenario,
    LabelLeakageScenario,
    # Outside the warehouse entirely.
    ApiBreakingChangeScenario,
    TrainingRegressionScenario,
    RiskyCommitScenario,
]

SCENARIOS: dict[str, type[BaseScenario]] = {s.name: s for s in _REGISTERED}


def all_scenarios() -> list[type[BaseScenario]]:
    return list(_REGISTERED)


def get(name: str) -> type[BaseScenario] | None:
    return SCENARIOS.get(name)


def names() -> list[str]:
    return list(SCENARIOS)
