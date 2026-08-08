"""PagerDuty Events API v2 client — trigger and resolve incidents."""
from __future__ import annotations

import json
import urllib.request
from typing import Optional

from agent.contracts import (
    AutonomyTier,
    ContextBundle,
    Incident,
    RootCauseAnalysis,
)
from agent.integrations.pagerduty.config import PagerDutyConfig
from agent.tools.graph.urns import short_name

_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"


class PagerDutyClient:
    def __init__(self, config: PagerDutyConfig) -> None:
        self.config = config

    def should_page(self, tier: AutonomyTier) -> bool:
        return tier.value in [t.lower() for t in self.config.page_on_tiers]

    def trigger(
        self,
        incident: Incident,
        context: ContextBundle,
        rca: RootCauseAnalysis,
        tier: AutonomyTier,
        reason: str,
    ) -> Optional[str]:
        if not self.should_page(tier):
            print(f"  [pagerduty] not paging — tier {tier.value} is not in "
                  f"{self.config.page_on_tiers}")
            return None

        severity = self.config.severity_map.get(
            rca.confidence or "low", "critical"
        )

        asset_name = short_name(incident.asset_urn) or incident.asset_urn
        summary = (f"[Sentinel] {asset_name}: {incident.summary} "
                   f"— {reason}")

        owners = ", ".join(context.owners) if context.owners else "unowned"
        downstream = len(context.downstream)

        payload = {
            "routing_key": self.config.routing_key,
            "event_action": "trigger",
            "dedup_key": f"sentinel-{incident.id}",
            "payload": {
                "summary": summary[:1024],
                "severity": severity,
                "source": "sentinel-agent",
                "component": asset_name,
                "group": rca.change_type.value if rca.change_type else "unknown",
                "custom_details": {
                    "incident_id": incident.id,
                    "asset_urn": incident.asset_urn,
                    "root_cause": rca.narrative,
                    "confidence": rca.confidence,
                    "tier": tier.value,
                    "owners": owners,
                    "downstream_count": downstream,
                    "blast_radius": [short_name(n.urn) or n.urn
                                     for n in context.downstream[:10]],
                },
            },
        }

        dedup_key = self._send(payload)
        if dedup_key:
            print(f"  [pagerduty] paged: {summary[:80]}")
        return dedup_key

    def resolve(self, incident_id: str) -> bool:
        payload = {
            "routing_key": self.config.routing_key,
            "event_action": "resolve",
            "dedup_key": f"sentinel-{incident_id}",
        }
        result = self._send(payload)
        if result:
            print(f"  [pagerduty] resolved: sentinel-{incident_id}")
        return result is not None

    def _send(self, payload: dict) -> Optional[str]:
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            _EVENTS_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return data.get("dedup_key")
        except Exception as exc:
            print(f"  [pagerduty] failed: {exc}")
            return None
