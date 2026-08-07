"""Deliberately breaking things, to prove the loop actually heals them.

An agent nobody has watched fail is an agent nobody should trust. A fire drill
runs the whole thing under real conditions on demand — break the pipeline,
detect, root-cause, mitigate, validate — so the claim that it works is something
you can re-check on a Tuesday rather than something demonstrated once.

The scenarios already know how to break things, so this is a thin adapter rather
than a second implementation. The import is deliberately lazy: the agent is the
product and the scenarios are the test harness, so nothing in the agent should
require the harness to be present in order to start.
"""
from __future__ import annotations

from typing import Optional

from agent.contracts import Incident


class FailureInjector:
    def __init__(self, reingest: bool = True) -> None:
        # DataHub-sourced detectors read the graph, so an injection that skips
        # the refresh is invisible to them — the drill would "pass" by seeing
        # nothing at all.
        self.reingest = reingest

    def available(self) -> list[str]:
        try:
            from scenarios import registry
        except ImportError:
            return []
        return registry.names()

    def inject(self, scenario_name: str) -> str:
        """Run one scenario. Returns a description, or '' if it is unknown."""
        try:
            from scenarios import registry
        except ImportError:
            return ""

        cls = registry.get(scenario_name)
        if cls is None:
            return ""
        cls().apply(reingest_after=self.reingest)
        return f"injected {scenario_name}"

    def expected_signal(self, scenario_name: str) -> Optional[str]:
        """What the scenario says the agent ought to notice — the drill's pass
        condition, declared by the scenario rather than by the drill."""
        try:
            from scenarios import registry
        except ImportError:
            return None
        cls = registry.get(scenario_name)
        return cls.expectation.signal_type if cls else None


def first_matching(incidents: list[Incident],
                   signal_type: Optional[str]) -> Optional[Incident]:
    """The incident a drill was trying to provoke, if it showed up."""
    if not incidents:
        return None
    if signal_type is None:
        return incidents[0]
    for inc in incidents:
        if inc.signal_type.value == signal_type:
            return inc
    return None
