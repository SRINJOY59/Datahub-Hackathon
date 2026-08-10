"""RCA engine — composes probes + memory recall into a grounded, structured
RootCauseAnalysis.

Flow:
  1. run every probe that applies_to the incident -> Evidence[]
  2. pick the deterministic root cause: the anomalous column furthest upstream,
     or — for table-level incidents with no column to blame — the kind of change
     the signal itself implies (SIGNAL_TO_CHANGE)
  3. recall similar past incidents from memory (precedent)
  4. LLM synthesizes a narrative over evidence + precedent (never invents facts)

Adding a new incident class = registering a new probe, and adding one row to
SIGNAL_TO_CHANGE if the class has no column-level symptom. The engine is
unchanged.
"""
from __future__ import annotations

from typing import Optional

from agent.contracts import (
    ChangeType,
    ContextBundle,
    Evidence,
    Incident,
    MemoryStore,
    PriorIncident,
    RootCauseAnalysis,
    SignalType,
)
from agent.llm import LLMClient, TaskType
from agent.prompts.rca import RCA_PROMPT, RCA_SYSTEM
from agent.registry import build_probes
from agent.schemas import RCAResult
from agent.tools.graph.column_lineage import ColumnLineageTool
from agent.tools.graph.urns import is_dataset, sibling_dataset_urn

# import the plugin packages so their decorators register
import agent.tools.probes  # noqa: F401
import agent.tools.detectors  # noqa: F401

# What kind of change each signal implies, when no probe has pinned an anomalous
# column. Some incidents are table-level facts — a feed that stopped, a batch
# that arrived at a tenth of its size — and have no column to blame, so without
# this they would fall through to UNKNOWN and the planner would reach for its
# do-nothing fallback. A new signal type gets its remediation by adding a row.
SIGNAL_TO_CHANGE: dict[SignalType, ChangeType] = {
    SignalType.DEPENDENCY_CHANGE: ChangeType.DEPENDENCY_CHANGE,
    SignalType.CODE_CHANGE: ChangeType.CODE_CHANGE,
    SignalType.TRAINING_REGRESSION: ChangeType.TRAINING_REGRESSION,
    SignalType.MODEL_DRIFT: ChangeType.MODEL_DRIFT,
    SignalType.FRESHNESS: ChangeType.FRESHNESS_LAG,
    SignalType.VOLUME_ANOMALY: ChangeType.VOLUME_ANOMALY,
    SignalType.LABEL_LEAKAGE: ChangeType.LABEL_LEAKAGE,
    SignalType.TRAINING_SERVING_SKEW: ChangeType.TRAINING_SERVING_SKEW,
    # ASSERTION_FAILURE and SCHEMA_CHANGE are deliberately absent: a failed
    # assertion says something is wrong, not what, so those are left to the
    # profiler's column-level classification rather than guessed from the signal.
}


class RCAEngine:
    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        memory: Optional[MemoryStore] = None,
        gms_server: str = "http://localhost:8080",
    ) -> None:
        self.llm = llm or LLMClient.for_task(TaskType.REASONING)
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
            root_asset = self._asset_urn(incident, root)
            measured = True
        else:
            # No column-level anomaly. The signal itself may still say what kind
            # of change this is; only fall back to UNKNOWN (and the LLM) when it
            # genuinely doesn't.
            change_type = SIGNAL_TO_CHANGE.get(incident.signal_type,
                                               ChangeType.UNKNOWN)
            measured = change_type is not ChangeType.UNKNOWN
            root_column, root_asset = None, self._root_asset_without_column(
                incident, evidence)

        precedents = (self.memory.recall(incident, context, change_type.value)
                      if self.memory else [])

        result = self._synthesize(incident, context, evidence, precedents)

        if change_type is ChangeType.UNKNOWN and result:
            change_type = _safe_change_type(result.change_type)

        narrative = (result.root_cause if result
                     else self._deterministic_narrative(incident, evidence, change_type))

        # Confidence describes how sure we are of the *classification*, so it
        # belongs to whatever produced it. When a probe measured the anomaly or
        # the signal itself names the change, that is arithmetic — 3218 rows
        # against a baseline of 8000 is not a judgement call, and letting the
        # LLM's prose confidence override it made the autonomy tier vary between
        # identical runs, so the same incident was sometimes repaired and
        # sometimes only contained. The model decides confidence only when it
        # also decided the classification.
        if measured:
            confidence = "high"
        elif result:
            confidence = result.confidence
        else:
            confidence = "low"
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
            upstream_path=self._upstream_path(incident),
            blast_radius=[n.name for n in context.downstream],
            recommended_mitigation=mitigation,
            precedents=[p.incident_id for p in precedents],
        )

    # ------------------------------------------------------------------ #
    def _upstream_path(self, incident: Incident) -> list[str]:
        """The table path from the incident asset to its source, for the report.

        Only datasets have a table lineage to walk; asking for the upstream path
        of a model urn returns a one-element path made of the model's own name,
        which reads like real lineage and is not. A transient graph failure here
        returns an empty path rather than sinking the whole analysis — same
        posture as a flaky probe.
        """
        if not (self.lineage and is_dataset(incident.asset_urn)):
            return []
        try:
            return self.lineage.table_upstream_path(incident.asset_urn)
        except Exception:
            return []

    @staticmethod
    def _pick_root(evidence: list[Evidence]) -> Optional[Evidence]:
        data_ev = [e for e in evidence if e.data.get("column")]
        if not data_ev:
            return None
        # deepest upstream anomaly is the origin, not a derived symptom
        return max(data_ev, key=lambda e: e.data.get("depth", 0))

    @staticmethod
    def _asset_urn(incident: Incident, root: Evidence) -> str:
        """The urn of the asset a probe blamed.

        A probe that already knows the dataset it profiled says so, and is
        believed. Otherwise the urn is rebuilt from a sibling of the incident's
        own asset — which only works when that asset *is* a dataset. Model-level
        incidents (drift, leakage, skew) carry an mlModel urn, and rebuilding a
        dataset urn from a model name would invent an asset that does not exist,
        then use it as an action target and a memory key.
        """
        known = root.data.get("dataset_urn")
        if known:
            return known
        table = root.data.get("table")
        if table and is_dataset(incident.asset_urn):
            return sibling_dataset_urn(incident.asset_urn, table)
        return incident.asset_urn

    @staticmethod
    def _root_asset_without_column(incident: Incident,
                                   evidence: list[Evidence]) -> str:
        """For table-level incidents, blame the deepest asset any probe named —
        a stale feed originates at the source, not where it was noticed."""
        located = [e for e in evidence if e.data.get("dataset_urn")]
        if not located:
            return incident.asset_urn
        deepest = max(located, key=lambda e: e.data.get("depth", 0))
        return deepest.data["dataset_urn"]

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
