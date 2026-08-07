"""Detector: the feed stopped delivering.

The purest silent failure. Old data is still valid data — no null, no range
violation, no duplicate — so every dbt assertion passes while the pipeline serves
answers about a world that has moved on.

Lag is measured against the newest row recorded in the healthy baseline, not
against the wall clock. The warehouse here is seeded with synthetic transactions
whose timestamps are already days behind "now", so a clock-based check would fire
permanently and mean nothing. Comparing to the baseline asks the question that
actually matters: has the newest data gone *backwards* since we last knew things
were fine?
"""
from __future__ import annotations

from datetime import datetime, timezone

from agent.contracts import Incident, SignalType
from agent.registry import detector
from agent.tools.graph.urns import sibling_dataset_urn
from agent.tools.warehouse.baselines import BaselineStore

# How far behind the baseline a table may fall before it counts as stale.
MAX_LAG_HOURS = 24.0

# Any dbt dataset urn from this pipeline, used to build sibling urns by name.
_URN_TEMPLATE = ("urn:li:dataset:(urn:li:dataPlatform:dbt,"
                 "fraud_demo.fraud.main.raw_transactions,PROD)")


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


@detector
class FreshnessDetector:
    name = "freshness"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.baselines = BaselineStore()

    def detect(self) -> list[Incident]:
        baseline = self.baselines.load()
        if not baseline:
            return []  # no idea what fresh looks like, so no claim either way
        current = self.baselines.current()

        stale: list[tuple[str, float, str, str]] = []
        for table, base in baseline.items():
            now = current.get(table)
            base_ts, now_ts = _parse(base.max_timestamp), None
            if base_ts is None or now is None:
                continue
            now_ts = _parse(now.max_timestamp)
            if now_ts is None:
                stale.append((table, float("inf"), base.max_timestamp or "", "none"))
                continue
            lag = (base_ts - now_ts).total_seconds() / 3600.0
            if lag > MAX_LAG_HOURS:
                stale.append((table, lag, base.max_timestamp or "",
                              now.max_timestamp or ""))

        if not stale:
            return []

        # Blame the source, not the symptom: every table downstream of a stopped
        # feed looks equally stale, and only the deepest one is the cause.
        worst = max(stale, key=lambda s: s[1])
        table, lag, expected, actual = worst

        return [Incident(
            id=f"STALE-{abs(hash(table)) % 10000:04d}",
            asset_urn=sibling_dataset_urn(_URN_TEMPLATE, table),
            signal_type=SignalType.FRESHNESS,
            detected_at=datetime.now(timezone.utc),
            summary=(f"{table} is {lag:.0f}h behind its baseline "
                     f"(newest row {actual}, expected around {expected}); "
                     f"{len(stale)} table(s) affected"),
            raw_evidence={
                "stale_tables": [
                    {"table": t, "lag_hours": l, "expected": e, "actual": a}
                    for t, l, e, a in stale
                ],
                "max_lag_hours": MAX_LAG_HOURS,
            },
        )]
