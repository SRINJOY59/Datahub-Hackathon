"""Detector: the batch arrived at the wrong size.

A partial delivery passes every quality check ever written for this pipeline. The
rows that did arrive are perfectly valid; there are simply far fewer of them than
there should be, so every average is computed over a sliver of the population and
the model trains on a fraction of its data. Nothing in dbt notices, because
nothing in dbt is counting.

The mirror case matters too: a batch delivered twice shows up as a volume jump,
which is a cheaper signal than waiting for the uniqueness assertion downstream.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agent.contracts import Incident, SignalType
from agent.registry import detector
from agent.tools.graph.urns import sibling_dataset_urn
from agent.tools.warehouse.baselines import BaselineStore

DROP_TOLERANCE = 0.25    # a quarter of the rows missing is a collapse
GROWTH_TOLERANCE = 0.50  # half again as many is a re-delivery

_URN_TEMPLATE = ("urn:li:dataset:(urn:li:dataPlatform:dbt,"
                 "fraud_demo.fraud.main.raw_transactions,PROD)")


@detector
class VolumeAnomalyDetector:
    name = "volume_anomaly"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.baselines = BaselineStore()

    def detect(self) -> list[Incident]:
        baseline = self.baselines.load()
        if not baseline:
            return []
        current = self.baselines.current()

        anomalies: list[tuple[str, float, int, int]] = []
        for table, base in baseline.items():
            now = current.get(table)
            if now is None or not base.row_count:
                continue
            shift = (now.row_count - base.row_count) / base.row_count
            if shift <= -DROP_TOLERANCE or shift >= GROWTH_TOLERANCE:
                anomalies.append((table, shift, base.row_count, now.row_count))

        if not anomalies:
            return []

        # The largest relative move is the origin; the rest are its shadow
        # downstream.
        worst = max(anomalies, key=lambda a: abs(a[1]))
        table, shift, expected, actual = worst
        direction = "collapsed" if shift < 0 else "inflated"

        return [Incident(
            id=f"VOL-{abs(hash(table)) % 10000:04d}",
            asset_urn=sibling_dataset_urn(_URN_TEMPLATE, table),
            signal_type=SignalType.VOLUME_ANOMALY,
            detected_at=datetime.now(timezone.utc),
            summary=(f"{table} row count {direction}: {actual} vs {expected} "
                     f"baseline ({shift:+.0%}); {len(anomalies)} table(s) affected"),
            raw_evidence={
                "volume_anomalies": [
                    {"table": t, "shift": s, "expected": e, "actual": a}
                    for t, s, e, a in anomalies
                ],
                "drop_tolerance": DROP_TOLERANCE,
                "growth_tolerance": GROWTH_TOLERANCE,
            },
        )]
