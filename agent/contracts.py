"""The contract between the two planes of Sentinel.

  MECHANISM plane (this repo's owner) implements `Mechanisms` — the things the
  system can physically do: read the graph, run checks, act, undo, open a PR,
  write back. Dumb and reversible.

  POLICY plane (partner) consumes `Mechanisms` via the orchestrator — deciding
  WHAT to do, in what order, and how to undo it.

Both sides code against the dataclasses + Protocol here. `fakes.py` provides a
canned implementation so the policy plane can run end-to-end before the real
mechanisms land. Do not rename fields without telling the other side.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Protocol


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class SignalType(str, Enum):
    ASSERTION_FAILURE = "assertion_failure"
    SCHEMA_CHANGE = "schema_change"
    FRESHNESS = "freshness"
    MODEL_DRIFT = "model_drift"
    DEPENDENCY_CHANGE = "dependency_change"    # external package / API breaking change
    CODE_CHANGE = "code_change"                # a commit altered a transform/model
    TRAINING_REGRESSION = "training_regression"  # model eval metric regressed


class ActionType(str, Enum):
    REPOINT_MODEL = "repoint_model"      # swap deployment to last-good model version
    PIN_FEATURE = "pin_feature"          # freeze a feature table to a snapshot
    PAUSE_JOB = "pause_job"              # stop a downstream job
    TAG_ASSET = "tag_asset"             # mark downstream "do-not-trust"
    QUARANTINE = "quarantine"           # isolate a bad partition


class AutonomyTier(str, Enum):
    AUTO = "auto"            # small blast radius, non-critical -> full auto
    PR_ONLY = "pr_only"      # Tier-Critical -> code fix via human-approved PR
    HUMAN_ONLY = "human_only"  # PII / high blast radius -> page a human


class ChangeType(str, Enum):
    """The deterministically-classified anomaly behind an incident."""
    NULL_SPIKE = "null_spike"            # null rate jumped in the recent batch
    SCALE_SHIFT = "scale_shift"          # unit/scale error (e.g. cents vs dollars)
    RANGE_VIOLATION = "range_violation"  # values outside a plausible range
    SCHEMA_CHANGE = "schema_change"      # column dropped / renamed / retyped
    DISTRIBUTION_DRIFT = "distribution_drift"  # subtle shift, no hard violation
    DEPENDENCY_CHANGE = "dependency_change"    # external package / API break
    CODE_CHANGE = "code_change"                # a source change altered behavior
    TRAINING_REGRESSION = "training_regression"  # model eval metric regressed
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------- #
# Data objects (the nouns crossing the seam)
# --------------------------------------------------------------------------- #
@dataclass
class Incident:
    id: str
    asset_urn: str
    signal_type: SignalType
    detected_at: datetime
    summary: str
    raw_evidence: dict = field(default_factory=dict)


@dataclass
class LineageNode:
    urn: str
    name: str
    entity_type: str  # dataset | mlModel | mlModelDeployment | dataJob


@dataclass
class ContextBundle:
    asset_urn: str
    name: str
    entity_type: str
    upstream: list[LineageNode] = field(default_factory=list)
    downstream: list[LineageNode] = field(default_factory=list)
    schema_fields: list[str] = field(default_factory=list)
    owners: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    failed_assertions: list[str] = field(default_factory=list)


@dataclass
class ActionRecord:
    action_type: ActionType
    target: str
    params: dict = field(default_factory=dict)
    inverse: Optional["ActionRecord"] = None  # populated by act(); replayed by undo()
    applied_at: Optional[datetime] = None
    note: str = ""


@dataclass
class ValidationResult:
    passed: bool
    checks_run: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


@dataclass
class ColumnProfile:
    """A snapshot of one column's health, split recent-vs-historical."""
    dataset_urn: str
    table: str
    column: str
    null_rate: float = 0.0
    recent_null_rate: float = 0.0
    mean: Optional[float] = None
    recent_mean: Optional[float] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    distinct: Optional[int] = None
    exists: bool = True
    note: str = ""


@dataclass
class Evidence:
    """A grounded fact produced by a probe. The LLM reasons over these; it does
    not invent them."""
    probe: str                     # which probe produced it
    kind: str                      # e.g. change_type value, "column_lineage"
    summary: str                   # human-readable, goes into the prompt
    data: dict = field(default_factory=dict)
    confidence: str = "medium"


@dataclass
class PriorIncident:
    """A past incident recalled from memory (the graph gets smarter each time)."""
    incident_id: str
    asset_urn: str
    root_cause: str
    change_type: str = ""
    resolution: str = ""
    when: str = ""


@dataclass
class RootCauseAnalysis:
    """Structured output of the RCA engine — grounded in real evidence."""
    incident_id: str
    root_cause_asset: str          # urn of the asset where the change originated
    root_cause_column: Optional[str]
    change_type: ChangeType
    confidence: str                # low | medium | high
    narrative: str                 # LLM synthesis over the evidence
    evidence: list[str] = field(default_factory=list)
    upstream_path: list[str] = field(default_factory=list)  # tables walked
    blast_radius: list[str] = field(default_factory=list)
    recommended_mitigation: str = ""
    precedents: list[str] = field(default_factory=list)  # prior incident ids cited


@dataclass
class PostMortem:
    incident_id: str
    asset_urn: str
    root_cause: str
    blast_radius: list[str] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)
    resolution: str = ""
    resolved_at: Optional[datetime] = None


# --------------------------------------------------------------------------- #
# The mechanism interface (verbs). Implemented by fakes.py, then for real.
# --------------------------------------------------------------------------- #
class Mechanisms(Protocol):
    def detect_incidents(self) -> list[Incident]:
        """Trigger source: surface open incidents (e.g. failed DataHub assertions)."""
        ...

    def read_context(self, asset_urn: str) -> ContextBundle:
        """Read lineage, schema, owners, tags, failing assertions from the graph."""
        ...

    def run_checks(self, asset_urn: str) -> ValidationResult:
        """Re-run the asset's assertions / dbt tests."""
        ...

    def act(self, action: ActionRecord) -> ActionRecord:
        """Execute a reversible action; return it with `inverse` populated."""
        ...

    def undo(self, action: ActionRecord) -> bool:
        """Replay an action's inverse (rollback)."""
        ...

    def propose_fix(self, incident: Incident, context: ContextBundle,
                    root_cause: str) -> str:
        """Generate a code fix (e.g. for a dependency/API break or schema fix) and
        open a draft PR; return the PR URL or a local diff path."""
        ...

    def write_back(self, post_mortem: PostMortem) -> None:
        """Write the incident + post-mortem back into DataHub."""
        ...


# --------------------------------------------------------------------------- #
# Plugin interfaces — the extension surfaces of the investigation platform.
# New incident classes are added by registering new Detectors / Probes, and new
# memory backends by implementing MemoryStore. The RCA core does not change.
# --------------------------------------------------------------------------- #
class Detector(Protocol):
    """Emits Signals (Incidents) from a source: DataHub assertions, model drift,
    dependency changes, git commits, freshness, training metrics, ..."""
    name: str

    def detect(self) -> list[Incident]:
        ...


class Probe(Protocol):
    """Investigates a Signal and returns grounded Evidence. Column lineage, data
    profiling, dependency diff, git blame, schema history, model eval, env, ..."""
    name: str

    def applies_to(self, incident: Incident) -> bool:
        ...

    def investigate(self, incident: Incident, context: ContextBundle) -> list[Evidence]:
        ...


class MemoryStore(Protocol):
    """Pluggable incident memory. Default backend writes to DataHub; others may
    add vector recall or codebase indexing."""

    def record(self, post_mortem: PostMortem) -> None:
        ...

    def recall(self, incident: Incident, context: ContextBundle,
               change_type: Optional[str] = None) -> list[PriorIncident]:
        """Return prior incidents relevant to this one. When change_type is given,
        only incidents of the same kind are returned (so unrelated past incidents
        on the same asset don't mislead RCA)."""
        ...
