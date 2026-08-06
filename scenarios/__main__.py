"""Run an incident scenario or reset the pipeline.

    python -m scenarios list                 # list available scenarios
    python -m scenarios unit_bug             # inject the unit-bug incident
    python -m scenarios null_spike           # inject the null-spike incident
    python -m scenarios reset                # restore a clean, healthy pipeline

    add --no-reingest to skip the DataHub refresh (faster local iteration)
"""
from __future__ import annotations

import argparse

from scenarios.base import Scenario
from scenarios.null_spike import NullSpikeScenario
from scenarios.unit_bug import UnitBugScenario

SCENARIOS = {s.name: s for s in (UnitBugScenario, NullSpikeScenario)}


def main() -> None:
    ap = argparse.ArgumentParser(prog="scenarios")
    ap.add_argument("action", help="scenario name, 'reset', or 'list'")
    ap.add_argument("--no-reingest", action="store_true")
    args = ap.parse_args()

    reingest_after = not args.no_reingest

    if args.action == "list":
        for name, cls in SCENARIOS.items():
            print(f"  {name:12s} {cls.description}")
        return
    if args.action == "reset":
        Scenario.reset(reingest_after=reingest_after)
        return
    if args.action not in SCENARIOS:
        raise SystemExit(f"unknown scenario '{args.action}'. "
                         f"Options: {', '.join(SCENARIOS)}, reset, list")

    SCENARIOS[args.action]().apply(reingest_after=reingest_after)


if __name__ == "__main__":
    main()
