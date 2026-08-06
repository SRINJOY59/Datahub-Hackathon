"""Probe: for a dependency/API breaking change, report the affected code usages
and the downstream DataHub assets they impact.
"""
from __future__ import annotations

from agent.contracts import ContextBundle, Evidence, Incident
from agent.registry import probe

_CODE_SIGNALS = {"dependency_change", "code_change"}


@probe
class DependencyImpactProbe:
    name = "dependency_impact"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        pass

    def applies_to(self, incident: Incident) -> bool:
        return incident.signal_type.value in _CODE_SIGNALS

    def investigate(self, incident: Incident, context: ContextBundle) -> list[Evidence]:
        ev = incident.raw_evidence or {}
        adv = ev.get("advisory", {})
        usages = ev.get("usages", [])
        impacted = ev.get("impacted_assets", [])

        evidence: list[Evidence] = []
        if adv:
            evidence.append(Evidence(
                probe=self.name,
                kind="dependency_change",
                summary=(f"{adv.get('package')} {adv.get('from_version')} -> "
                         f"{adv.get('to_version')}: {adv.get('summary')}. "
                         f"Migration: {adv.get('migration')}"),
                data={"advisory": adv},
                confidence="high",
            ))
        for u in usages[:10]:
            evidence.append(Evidence(
                probe=self.name,
                kind="code_usage",
                summary=f"affected usage {u['file']}:{u['line']}  {u['code']}",
                data=u,
                confidence="high",
            ))
        if impacted:
            names = [a.split(",")[1] if "," in a else a for a in impacted]
            evidence.append(Evidence(
                probe=self.name,
                kind="impacted_assets",
                summary=f"impacted DataHub assets: {names}",
                data={"impacted_assets": impacted},
                confidence="high",
            ))
        return evidence
