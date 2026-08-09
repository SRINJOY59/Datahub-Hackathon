"""GraphQL types — the shape a dashboard actually queries.

These mirror agent/store/incidents.py's row shape and agent/journal.py's
ActionRecord, but deliberately thinner: a dashboard wants "is this reversible",
not the nested inverse ActionRecord that answers it internally.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import strawberry


@strawberry.type
class ActionEntry:
    action_type: str
    target: str
    status: str
    note: str
    reversible: bool
    applied_at: Optional[datetime]


@strawberry.type
class Incident:
    id: str
    asset_urn: str
    asset_name: Optional[str]
    signal_type: Optional[str]
    summary: Optional[str]
    change_type: Optional[str]
    confidence: Optional[str]
    narrative: Optional[str]
    root_cause_asset: Optional[str]
    root_cause_column: Optional[str]
    tier: Optional[str]
    status: str
    resolved: bool
    pr: Optional[str]
    cost_usd: Optional[float]
    cost_basis: Optional[str]
    downstream_count: Optional[int]
    action_types: list[str]  # the summary list already on the outcome
    detected_at: datetime
    closed_at: Optional[datetime]
    updated_at: datetime
    # Populated by the resolver from the action journal, joined on incident_id.
    timeline: list[ActionEntry] = strawberry.field(default_factory=list)

    @strawberry.field
    def minutes_to_close(self) -> Optional[float]:
        if not self.closed_at:
            return None
        return (self.closed_at - self.detected_at).total_seconds() / 60


@strawberry.type
class ChangeTypeCount:
    change_type: str
    count: int


@strawberry.type
class Stats:
    total: int
    resolved: int
    open: int
    exposure_usd: float
    mttr_minutes: Optional[float]
    by_change_type: list[ChangeTypeCount]


@strawberry.type
class DayPoint:
    day: str
    total: int
    resolved: int
    exposure_usd: float
    mttr_minutes: Optional[float]


@strawberry.type
class ActionCount:
    action_type: str
    count: int


@strawberry.type
class SavingsDigest:
    incidents: int
    actions_applied: int
    actions_simulated: int
    actions_failed: int
    hours_saved: float
    shadow_mode: bool
    by_action: list[ActionCount]


@strawberry.type
class TrustBadge:
    asset_urn: str
    asset_name: str
    score: float
    grade: str
    failed_assertions: int
    open_incident: bool
    volume_shift: float
    freshness_lag_hours: float
    past_incidents: int


@strawberry.type
class Runbook:
    change_type: str
    skill_urn: Optional[str]
    registered: bool
    title: Optional[str]
    description: Optional[str]
    instructions: Optional[str]
    incidents_backing: int
    incidents_needed: int


@strawberry.type
class JournalEntry:
    action_type: str
    target: str
    status: str
    note: str
    incident_id: str
    reversible: bool
    applied_at: Optional[str]


@strawberry.type
class WebhookRun:
    run_id: str
    asset_urn: str
    source: str
    status: str
    started_at: Optional[str]
    finished_at: Optional[str]
    error: Optional[str]


@strawberry.type
class WebhookActivity:
    attached: bool
    active: list[WebhookRun]
    recent: list[WebhookRun]


@strawberry.type
class Dependency:
    package: str
    installed_version: Optional[str]
    files_using: int
    impacted_assets: int
    asset_urns: list[str]
    has_advisory: bool
    status: str  # healthy | at_risk | unknown


@strawberry.type
class AdvisoryUsage:
    file: str
    line: int
    code: str


@strawberry.type
class Advisory:
    id: str
    package: str
    import_name: str
    from_version: str
    to_version: str
    kind: str
    summary: str
    migration: str
    symbols: list[str]
    usages: list[AdvisoryUsage]
    usages_count: int
    impacted_assets: list[str]
    impacted_count: int
    published_at: str


@strawberry.type
class Migration:
    incident_id: str
    asset_urn: str
    asset_name: Optional[str]
    status: str
    resolved: bool
    pr: Optional[str]
    cost_usd: Optional[float]
    narrative: str
    detected_at: str
    closed_at: Optional[str]
    has_diff: bool
    diff_preview: str


@strawberry.type
class BlastRadiusNode:
    urn: str
    name: str
    entity_type: str
    upstream_of: str


@strawberry.type
class BlastRadius:
    package: str
    files: list[str]
    direct_assets: list[str]
    downstream_assets: list[BlastRadiusNode]
    total_impacted: int


@strawberry.type
class ApiHealthStats:
    total_dependencies: int
    at_risk: int
    healthy: int
    active_advisories: int
    resolved_migrations: int
    pending_migrations: int
    total_affected_usages: int


@strawberry.type
class DependencyScanResult:
    scanned: bool
    advisories_checked: int
    incidents_found: int
    error: Optional[str] = None


@strawberry.type
class RegistrySyncItem:
    package: str
    path: str
    source: str


@strawberry.type
class RegistrySyncResult:
    success: bool
    packages_checked: int
    advisories_generated: int
    network_online: bool
    error: Optional[str] = None
    generated: list[RegistrySyncItem] = strawberry.field(default_factory=list)


@strawberry.type
class SystemStatus:
    """What is actually alive, for the dashboard's health panel — not
    aspirational config, observed state (or, for integrations, whether a
    credential is present, since checking a live connection would mean
    triggering side effects like opening a Socket Mode session just to
    answer a status query)."""
    datahub_reachable: bool
    datahub_version: Optional[str]
    datahub_url: str
    slack_configured: bool
    slack_interactive_approvals: bool
    pagerduty_configured: bool
    llm_configured: bool
    llm_model: str
    webhook_sources_enabled: list[str]
    sweep_interval_minutes: int
