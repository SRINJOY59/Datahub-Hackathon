"""Run an incident scenario, capture a baseline, or reset the pipeline.

    python -m scenarios list                 # list available scenarios
    python -m scenarios unit_bug             # inject the unit-bug incident
    python -m scenarios reset                # restore a clean, healthy pipeline
    python -m scenarios snapshot             # capture the last-known-good state

    add --no-reingest to skip the DataHub refresh (faster local iteration)
"""
from __future__ import annotations

import argparse

from scenarios import registry
from scenarios.base import PipelineReset, capture_last_good


def main() -> None:
    try:
        from agent.console import enable_utf8

        enable_utf8()
    except ImportError:
        pass

    ap = argparse.ArgumentParser(prog="scenarios")
    ap.add_argument("action", help="scenario name, 'reset', 'snapshot', or 'list'")
    ap.add_argument("--no-reingest", action="store_true")
    args = ap.parse_args()

    reingest_after = not args.no_reingest

    if args.action == "list":
        for cls in registry.all_scenarios():
            silent = "" if cls.expectation.trips_dbt_tests else "  [silent: dbt stays green]"
            print(f"  {cls.name:22s} {cls.description}{silent}")
        return
    if args.action == "reset":
        PipelineReset().run(reingest_after=reingest_after)
        return
    if args.action == "snapshot":
        capture_last_good()
        return

    cls = registry.get(args.action)
    if cls is None:
        raise SystemExit(f"unknown scenario '{args.action}'. "
                         f"Options: {', '.join(registry.names())}, reset, snapshot, list")

    cls().apply(reingest_after=reingest_after)


if __name__ == "__main__":
    main()
