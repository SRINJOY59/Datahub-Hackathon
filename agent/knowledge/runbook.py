"""Turning repeated incidents into a runbook other agents can use.

Every resolved incident leaves a post-mortem on the asset. Individually they are
a record; collectively they are a procedure — the same class of failure, handled
the same way, several times over. This reads them back and asks the model to
write down the procedure that is already implicit in them.

The result is registered in DataHub as an **AgentSkill**, which is a real entity
type in the catalog with a `name`, a `description` and an `instructions` field.
That matters more than the file it could have been: a runbook that lives beside
the assets it applies to is discoverable by the next person *and* the next agent,
which is the difference between institutional memory and a wiki page.
"""
from __future__ import annotations

import time
from typing import Optional

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    AgentSkillInfoClass,
    AuditStampClass,
    InstitutionalMemoryClass,
)

from agent.llm import LLMClient
from agent.prompts.runbook import RUNBOOK_PROMPT, RUNBOOK_SYSTEM
from agent.schemas import Runbook

_ACTOR = "urn:li:corpuser:sentinel"
MIN_INCIDENTS = 2  # one incident is an anecdote, not a procedure


def skill_urn(change_type: str) -> str:
    return f"urn:li:agentSkill:sentinel-{change_type.replace('_', '-')}"


class RunbookSynthesizer:
    def __init__(self, gms_server: str = "http://localhost:8080",
                 llm: Optional[LLMClient] = None) -> None:
        self.graph = DataHubGraph(DataHubGraphConfig(server=gms_server))
        self.llm = llm or LLMClient()

    # ------------------------------------------------------------------ #
    def collect(self) -> dict[str, list[dict]]:
        """Every post-mortem Sentinel has written, grouped by kind of change."""
        import json

        from memory.datahub_memory import _MARKER

        grouped: dict[str, list[dict]] = {}
        try:
            urns = self.graph.get_urns_by_filter(entity_types=["dataset"],
                                                 platform="dbt")
        except Exception:
            return grouped

        seen: set[str] = set()
        for urn in list(urns):
            try:
                im = self.graph.get_aspect(urn, InstitutionalMemoryClass)
            except Exception:
                continue
            for element in (im.elements if im else []):
                try:
                    record = json.loads(element.description)
                except (ValueError, TypeError):
                    continue
                if not record.get(_MARKER):
                    continue
                key = f"{record.get('change_type')}:{record.get('incident_id')}"
                if key in seen:
                    continue
                seen.add(key)
                grouped.setdefault(record.get("change_type") or "unknown",
                                   []).append(record)
        return grouped

    def synthesize(self, change_type: str,
                   incidents: list[dict]) -> Optional[Runbook]:
        if len(incidents) < MIN_INCIDENTS or not self.llm.available():
            return None
        prompt = RUNBOOK_PROMPT.format(
            change_type=change_type,
            count=len(incidents),
            incidents="\n".join(
                f"- {i.get('incident_id')}: {i.get('root_cause')} "
                f"-> resolved by {i.get('resolution')} "
                f"(actions: {', '.join(i.get('actions') or [])})"
                for i in incidents
            ),
        )
        return self.llm.structured(prompt, Runbook, system=RUNBOOK_SYSTEM,
                                   max_tokens=1200)

    def register(self, change_type: str, runbook: Runbook,
                 incident_count: int) -> Optional[str]:
        """Publish the runbook as a DataHub AgentSkill."""
        urn = skill_urn(change_type)
        stamp = AuditStampClass(time=int(time.time() * 1000), actor=_ACTOR)
        try:
            self.graph.emit_mcp(MetadataChangeProposalWrapper(
                entityUrn=urn,
                aspect=AgentSkillInfoClass(
                    name=runbook.title,
                    description=(f"{runbook.summary} Synthesised by Sentinel from "
                                 f"{incident_count} resolved {change_type} "
                                 f"incident(s)."),
                    # The tool list lives inside the instructions: `requiredTools`
                    # holds DataHub urns, not prose, and rejects anything else.
                    instructions=runbook.as_instructions(),
                    created=stamp,
                    lastModified=stamp,
                ),
            ))
            return urn
        except Exception as e:
            print(f"  could not register runbook for {change_type}: "
                  f"{type(e).__name__}: {str(e)[:200]}")
            return None

    # ------------------------------------------------------------------ #
    def run(self) -> list[tuple[str, str, int]]:
        """Synthesise and register a runbook for every change type with enough
        history. Returns (change_type, skill_urn, incidents_used)."""
        registered: list[tuple[str, str, int]] = []
        for change_type, incidents in sorted(self.collect().items()):
            if len(incidents) < MIN_INCIDENTS:
                continue
            runbook = self.synthesize(change_type, incidents)
            if runbook is None:
                continue
            urn = self.register(change_type, runbook, len(incidents))
            if urn:
                registered.append((change_type, urn, len(incidents)))
        return registered
