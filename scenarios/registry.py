"""The one place that knows which scenarios exist.

Three consumers need this list — the CLI (`python -m scenarios`), the
verification harness, and the agent's fire-drill mechanism — so it does not live
in any of them.
"""
from __future__ import annotations

from scenarios.api_breaking_change import ApiBreakingChangeScenario
from scenarios.base import BaseScenario
from scenarios.distribution_drift import DistributionDriftScenario
from scenarios.null_spike import NullSpikeScenario
from scenarios.schema_change import SchemaChangeScenario
from scenarios.training_regression import TrainingRegressionScenario
from scenarios.unit_bug import UnitBugScenario

_REGISTERED: list[type[BaseScenario]] = [
    UnitBugScenario,
    NullSpikeScenario,
    DistributionDriftScenario,
    SchemaChangeScenario,
    ApiBreakingChangeScenario,
    TrainingRegressionScenario,
]

SCENARIOS: dict[str, type[BaseScenario]] = {s.name: s for s in _REGISTERED}


def all_scenarios() -> list[type[BaseScenario]]:
    return list(_REGISTERED)


def get(name: str) -> type[BaseScenario] | None:
    return SCENARIOS.get(name)


def names() -> list[str]:
    return list(SCENARIOS)
