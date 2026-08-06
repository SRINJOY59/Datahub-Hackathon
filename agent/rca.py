"""RCA engine — composes probes + memory recall into a grounded, structured
RootCauseAnalysis.

Flow:
  1. run every probe that applies_to the incident -> Evidence[]
  2. pick the deterministic root cause: the anomalous column furthest upstream
  3. recall similar past incidents from memory (precedent)
  4. LLM synthesizes a narrative over evidence + precedent (never invents facts)

Adding a new incident class = registering a new probe. The engine is unchanged.
"""
from __future__ import annotations

from typing import Optional

import datahub.emitter.mce_builder as builder

from agent.contracts import (
    ChangeType,
    ContextBundle,
    Evidence,
    Incident,
    MemoryStore,
    PriorIncident,
    RootCauseAnalysis,
)
from agent.llm import LLMClient
from agent.prompts.rca import RCA_PROMPT, RCA_SYSTEM
from agent.registry import build_probes
from agent.schemas import RCAResult
from agent.tools.graph.column_lineage import ColumnLineageTool

# import the plugin packages so their decorators register
import agent.tools.probes  # noqa: F401
import agent.tools.detectors  # noqa: F401


class RCAEngine:
    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        memory: Optional[MemoryStore] = None,
        gms_server: str = "http://localhost:8080",
    ) -> None:
        self.llm = llm
        self.memory = memory
        # tolerate DataHub being unreachable (e.g. offline --fake smoke test)
        try:
            self.probes = build_probes(gms_server)
            self.lineage: Optional[ColumnLineageTool] = ColumnLineageTool(gms_server)
        except Exception:
            self.probes = []
            self.lineage = None

    def analyze(self, incident: Incident, context: ContextBundle) -> RootCauseAnalysis:
        evidence: list[Evidence] = []
        for p in self.probes:
            if p.applies_to(incident):
                try:
                    evidence.extend(p.investigate(incident, context))
                except Exception:  # a flaky probe must not sink the analysis
                    pass

        root = self._pick_root(evidence)

        # Determine change_type / root asset FIRST, so memory recall can filter to
        # relevant precedent (same kind), not just the same asset.
        if root:
            change_type = ChangeType(root.data["change_type"])
            root_column = root.data["column"]
            root_asset = self._asset_urn(incident.asset_urn, root.data["table"])
        elif incident.signal_type.value in ("dependency_change", "code_change"):
            change_type = _safe_change_type(incident.signal_type.value)
            root_column, root_asset = None, incident.asset_urn
        elif incident.signal_type.value == "training_regression":
            change_type = ChangeType.TRAINING_REGRESSION
            root_column, root_asset = None, incident.asset_urn
        else:
            change_type = ChangeType.UNKNOWN  # refined from the LLM below
            root_column, root_asset = None, incident.asset_urn

        precedents = (self.memory.recall(incident, context, change_type.value)
                      if self.memory else [])

        result = self._synthesize(incident, context, evidence, precedents)

        if change_type is ChangeType.UNKNOWN and result:
            change_type = _safe_change_type(result.change_type)

        narrative = (result.root_cause if result
                     else self._deterministic_narrative(incident, evidence, change_type))
        confidence = (result.confidence if result else ("high" if root else "low"))
        mitigation = (result.recommended_mitigation if result
                      else _default_mitigation(change_type))

        return RootCauseAnalysis(
            incident_id=incident.id,
            root_cause_asset=root_asset,
            root_cause_column=root_column,
            change_type=change_type,
            confidence=confidence,
            narrative=narrative,
            evidence=[e.summary for e in evidence],
            upstream_path=(self.lineage.table_upstream_path(incident.asset_urn)
                           if self.lineage else []),
            blast_radius=[n.name for n in context.downstream],
            recommended_mitigation=mitigation,
            precedents=[p.incident_id for p in precedents],
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _pick_root(evidence: list[Evidence]) -> Optional[Evidence]:
        data_ev = [e for e in evidence if e.data.get("column")]
        if not data_ev:
            return None
        # deepest upstream anomaly is the origin, not a derived symptom
        return max(data_ev, key=lambda e: e.data.get("depth", 0))

    @staticmethod
    def _asset_urn(incident_asset_urn: str, table: str) -> str:
        name = incident_asset_urn.split(",")[1]
        prefix = name.rsplit(".", 1)[0]
        return builder.make_dataset_urn("dbt", f"{prefix}.{table}", "PROD")

    def _synthesize(self, incident, context, evidence, precedents) -> Optional[RCAResult]:
        """Structured LLM synthesis over evidence + precedent. Returns None (caller
        falls back to deterministic) when no LLM is configured or it can't produce
        valid JSON."""
        if not (self.llm and self.llm.available()):
            return None
        prompt = RCA_PROMPT.format(
            incident=incident.summary,
            context=_context_str(context),
            evidence=_evidence_str(evidence),
            precedent=_precedent_str(precedents),
        )
        return self.llm.structured(prompt, RCAResult, system=RCA_SYSTEM)

    @staticmethod
    def _deterministic_narrative(incident, evidence, change_type) -> str:
        return (f"{change_type.value} originating upstream; "
                + (evidence[0].summary if evidence else incident.summary))


def _safe_change_type(value: Optional[str]) -> ChangeType:
    try:
        return ChangeType(value) if value else ChangeType.UNKNOWN
    except ValueError:
        return ChangeType.UNKNOWN


def _default_mitigation(ct: ChangeType) -> str:
    return {
        ChangeType.NULL_SPIKE: "quarantine the latest partition and pin the feature to last-known-good",
        ChangeType.SCALE_SHIFT: "roll back the upstream change; pin the feature to last-known-good",
        ChangeType.SCHEMA_CHANGE: "restore the dropped/renamed column; open a fix PR",
        ChangeType.DISTRIBUTION_DRIFT: "repoint the model to the last-good version pending investigation",
    }.get(ct, "repoint the model to the last-good version and page the owner")


def _context_str(c: ContextBundle) -> str:
    return (f"asset: {c.name} ({c.entity_type}); tags: {c.tags}; owners: {c.owners}; "
            f"upstream: {[n.name for n in c.upstream]}; "
            f"downstream: {[n.name for n in c.downstream]}; "
            f"failed_assertions: {c.failed_assertions}")


def _evidence_str(ev: list[Evidence]) -> str:
    return "\n".join(f"- [{e.probe}] {e.summary}" for e in ev) or "- (no probe evidence)"


def _precedent_str(priors: list[PriorIncident]) -> str:
    if not priors:
        return "- (no similar past incidents on record)"
    return "\n".join(
        f"- {p.incident_id}: {p.root_cause} -> resolved by {p.resolution}" for p in priors
    )
