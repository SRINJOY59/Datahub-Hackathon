"""DataHub-backed incident memory.

record()  -> appends a structured post-mortem to the asset's institutionalMemory
             aspect (visible in the DataHub UI; inherited by anyone who opens the
             asset).
recall()  -> reads prior Sentinel post-mortems back off the asset (and, when
             available, its downstream model) so the next incident can cite them.

This is what makes the system compound: incident #2 on the same asset resolves
faster because the agent sees how #1 was handled.
"""
from __future__ import annotations

import json
import re
import time

from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    AuditStampClass,
    InstitutionalMemoryClass,
    InstitutionalMemoryMetadataClass,
)

from agent.contracts import Incident, ContextBundle, PostMortem, PriorIncident

_ACTOR = "urn:li:corpuser:sentinel"
_MARKER = "_sentinel_incident"


class DataHubMemory:
    def __init__(self, gms_server: str | None = None) -> None:
        from agent.gms import default_gms_server

        gms_server = gms_server or default_gms_server()
        self.graph = DataHubGraph(DataHubGraphConfig(server=gms_server))

    def record(self, pm: PostMortem) -> None:
        # root_cause is stored as "[change_type] narrative"; capture the type so
        # recall can filter to relevant precedent.
        m = re.match(r"\[([a-z_]+)\]", pm.root_cause or "")
        payload = json.dumps({
            _MARKER: True,
            "incident_id": pm.incident_id,
            "root_cause": pm.root_cause,
            "change_type": m.group(1) if m else "",
            "resolution": pm.resolution,
            "actions": pm.actions_taken,
            "blast_radius": pm.blast_radius,
            "when": (pm.resolved_at.isoformat() if pm.resolved_at else ""),
        })
        existing = self.graph.get_aspect(pm.asset_urn, InstitutionalMemoryClass) \
            or InstitutionalMemoryClass(elements=[])
        existing.elements.append(InstitutionalMemoryMetadataClass(
            url=f"https://sentinel.local/incident/{pm.incident_id}",
            description=payload,
            createStamp=AuditStampClass(time=int(time.time() * 1000), actor=_ACTOR),
        ))
        self.graph.emit(
            _mcp(pm.asset_urn, existing)
        )

    def recall(self, incident: Incident, context: ContextBundle,
               change_type: str | None = None) -> list[PriorIncident]:
        priors: list[PriorIncident] = []
        for urn in self._recall_urns(incident, context):
            im = self.graph.get_aspect(urn, InstitutionalMemoryClass)
            for el in (im.elements if im else []):
                rec = _parse(el.description)
                if not rec:
                    continue
                # relevance filter: only same-kind precedent (avoids unrelated
                # past incidents on the same asset misleading RCA). Derive the
                # kind from the record, or from the "[change_type]" root_cause
                # prefix for older records without the explicit field.
                rec_ct = rec.get("change_type")
                if not rec_ct:
                    m = re.match(r"\[([a-z_]+)\]", rec.get("root_cause", ""))
                    rec_ct = m.group(1) if m else ""
                if change_type and rec_ct and rec_ct != change_type:
                    continue
                priors.append(PriorIncident(
                    incident_id=rec.get("incident_id", ""),
                    asset_urn=urn,
                    root_cause=rec.get("root_cause", ""),
                    change_type=rec.get("change_type", ""),
                    resolution=rec.get("resolution", ""),
                    when=rec.get("when", ""),
                ))
        # newest first; exclude the current incident, dedupe by incident id
        priors = [p for p in priors if p.incident_id != incident.id]
        seen, deduped = set(), []
        for p in reversed(priors):
            if p.incident_id in seen:
                continue
            seen.add(p.incident_id)
            deduped.append(p)
        return deduped

    @staticmethod
    def _recall_urns(incident: Incident, context: ContextBundle) -> list[str]:
        urns = [incident.asset_urn]
        # also look at the downstream model, where post-mortems land on the card
        for n in context.downstream:
            if n.entity_type == "mlModel":
                urns.append(n.urn)
        return urns


def _mcp(urn: str, aspect):
    from datahub.emitter.mcp import MetadataChangeProposalWrapper

    return MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect)


def _parse(description: str) -> dict | None:
    try:
        rec = json.loads(description)
    except (ValueError, TypeError):
        return None
    return rec if rec.get(_MARKER) else None
