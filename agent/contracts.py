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

    def propose_fix(self, context: ContextBundle, root_cause: str) -> str:
        """Open a draft fix PR against the real schema; return the PR URL."""
        ...

    def write_back(self, post_mortem: PostMortem) -> None:
        """Write the incident + post-mortem back into DataHub."""
        ...
