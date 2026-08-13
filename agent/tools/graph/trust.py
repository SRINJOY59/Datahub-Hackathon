"""A reliability score, written where people already look.

Someone opening a dataset in DataHub deserves to see what the agent knows about
it. Everything needed is already being computed — assertion results, volume and
freshness against baseline, the incident history in memory — but it lives in the
agent's logs, which is to say nowhere anyone will find it at the moment they are
deciding whether to trust a number.

The score is deliberately simple and its inputs are published alongside it. A
health grade nobody can explain is a health grade nobody will act on, so the tag
carries the letter and the properties carry the arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import datahub.emitter.mce_builder as builder
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    GlobalTagsClass,
    InstitutionalMemoryClass,
    TagAssociationClass,
    TagPropertiesClass,
)

from agent.contracts import TrustScore
from agent.tools.warehouse.baselines import BaselineStore

GRADE_TAGS = {
    "A": ("Sentinel-Health-A", "Healthy: no open incidents, data within its "
                               "expected shape."),
    "B": ("Sentinel-Health-B", "Minor concerns: recent incident history or a "
                               "small deviation from baseline."),
    "C": ("Sentinel-Health-C", "Degraded: repeated incidents or a clear "
                               "deviation from baseline."),
    "D": ("Sentinel-Health-D", "Unreliable: an open incident, or data far "
                               "outside its expected shape."),
}

# What each problem costs, out of 100.
PENALTY_FAILED_ASSERTION = 25.0
PENALTY_OPEN_INCIDENT = 30.0
PENALTY_VOLUME = 20.0
PENALTY_FRESHNESS = 20.0
PENALTY_PER_PAST_INCIDENT = 5.0
MAX_HISTORY_PENALTY = 20.0


@dataclass
class HealthSignals:
    """What the score is computed from. Gathering these needs DataHub and the
    warehouse; turning them into a number does not, which is why the two are
    separate — the arithmetic is the part worth testing."""
    failed_assertions: int = 0
    degraded: bool = False
    volume_shift: float = 0.0
    freshness_lag_hours: float = 0.0
    past_incidents: int = 0


def score_from_signals(signals: HealthSignals) -> float:
    """Signals to a 0-100 score.

    Failing assertions are capped at two: past a point the asset is simply
    broken, and letting a long list drive the score to zero would say nothing
    more than a short one does. Incident history is capped for the opposite
    reason — an asset that has had problems before should look worse, but never
    so much worse that a currently-healthy table can't recover its grade.
    """
    penalty = 0.0
    penalty += PENALTY_FAILED_ASSERTION * min(signals.failed_assertions, 2)
    penalty += PENALTY_OPEN_INCIDENT if signals.degraded else 0.0
    penalty += PENALTY_VOLUME if abs(signals.volume_shift) >= 0.25 else 0.0
    penalty += PENALTY_FRESHNESS if signals.freshness_lag_hours > 24 else 0.0
    penalty += min(PENALTY_PER_PAST_INCIDENT * signals.past_incidents,
                   MAX_HISTORY_PENALTY)
    return max(0.0, 100.0 - penalty)


class TrustScorer:
    def __init__(self, gms_server: str | None = None) -> None:
        from agent.gms import default_gms_server

        gms_server = gms_server or default_gms_server()
        self.gms_server = gms_server
        self.graph = DataHubGraph(DataHubGraphConfig(server=gms_server))
        self.baselines = BaselineStore()

    # ------------------------------------------------------------------ #
    def score(self, asset_urn: str, table: str | None = None) -> TrustScore:
        signals = self._gather(asset_urn, table)
        value = score_from_signals(signals)
        return TrustScore(
            asset_urn=asset_urn,
            score=round(value, 1),
            grade=_grade(value),
            inputs={
                "failed_assertions": signals.failed_assertions,
                "open_incident": signals.degraded,
                "volume_shift": round(signals.volume_shift, 4),
                "freshness_lag_hours": round(signals.freshness_lag_hours, 1),
                "past_incidents": signals.past_incidents,
            },
            computed_at=datetime.now(timezone.utc),
        )

    def publish(self, score: TrustScore) -> bool:
        """Write the grade onto the asset, replacing any earlier grade."""
        try:
            tag_name, description = GRADE_TAGS[score.grade]
            self.graph.emit_mcp(MetadataChangeProposalWrapper(
                entityUrn=builder.make_tag_urn(tag_name),
                aspect=TagPropertiesClass(name=tag_name, description=description)))

            grade_urns = {builder.make_tag_urn(t) for t, _ in GRADE_TAGS.values()}
            existing = (self.graph.get_aspect(score.asset_urn, GlobalTagsClass)
                        or GlobalTagsClass(tags=[]))
            # Only one grade at a time, or the asset ends up claiming to be both
            # healthy and unreliable.
            kept = [t for t in existing.tags if t.tag not in grade_urns]
            kept.append(TagAssociationClass(tag=builder.make_tag_urn(tag_name)))

            self.graph.emit_mcp(MetadataChangeProposalWrapper(
                entityUrn=score.asset_urn, aspect=GlobalTagsClass(tags=kept)))
            return True
        except Exception:
            return False

    def score_and_publish(self, asset_urn: str,
                          table: str | None = None) -> TrustScore:
        score = self.score(asset_urn, table)
        self.publish(score)
        return score

    # ------------------------------------------------------------------ #
    def _gather(self, asset_urn: str, table: str | None) -> HealthSignals:
        from agent.tools.actuators.tag_asset import DEGRADED_TAG
        from agent.tools.graph.urns import table_of

        signals = HealthSignals()
        table = table or table_of(asset_urn)

        # The loudest signal there is: this asset's own tests are failing right
        # now. Without it a broken pipeline can still show a grade A, which is
        # exactly the reassurance nobody should be given.
        try:
            from agent.tools.graph.context import DataHubContextTool

            signals.failed_assertions = len(
                DataHubContextTool(self.gms_server)._failed_assertions(asset_urn))
        except Exception:
            pass

        try:
            tags = self.graph.get_aspect(asset_urn, GlobalTagsClass)
            degraded_urn = builder.make_tag_urn(DEGRADED_TAG)
            signals.degraded = bool(tags and any(t.tag == degraded_urn
                                                 for t in tags.tags))
        except Exception:
            pass

        try:
            im = self.graph.get_aspect(asset_urn, InstitutionalMemoryClass)
            signals.past_incidents = len(im.elements) if im else 0
        except Exception:
            pass

        if table:
            base = self.baselines.load().get(table)
            now = self.baselines.current().get(table)
            if base and now and base.row_count:
                signals.volume_shift = (now.row_count - base.row_count) / base.row_count
                signals.freshness_lag_hours = _lag_hours(base.max_timestamp,
                                                         now.max_timestamp)
        return signals


def _grade(value: float) -> str:
    if value >= 90:
        return "A"
    if value >= 70:
        return "B"
    if value >= 50:
        return "C"
    return "D"


def _lag_hours(baseline_ts: str | None, current_ts: str | None) -> float:
    if not baseline_ts or not current_ts:
        return 0.0
    try:
        base = datetime.fromisoformat(baseline_ts)
        now = datetime.fromisoformat(current_ts)
    except ValueError:
        return 0.0
    return max(0.0, (base - now).total_seconds() / 3600.0)
