"""Query root — reads the incident store and, for a single incident, joins
the action journal for its timeline.

The list resolver never joins the journal: ActionJournal.for_incident()
re-reads and re-parses the entire journal file per call (it has no index),
so doing that once per row in a 50-incident list would be fifty full-file
scans for data almost nothing renders. A detail view asking for one incident
is the cheap and the right place to pay that cost.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import strawberry

from agent.journal import ActionJournal
from agent.store import IncidentStore, shared_store
from api import api_health, insights
from api.types import (
    ActionCount,
    ActionEntry,
    Advisory,
    AdvisoryUsage,
    ApiHealthStats,
    BlastRadius,
    BlastRadiusNode,
    ChangeTypeCount,
    DayPoint,
    Dependency,
    DependencyScanResult,
    Incident,
    JournalEntry,
    Migration,
    RegistrySyncItem,
    RegistrySyncResult,
    RemediateAdvisoryResult,
    Runbook,
    SavingsDigest,
    Stats,
    SweepStatus,
    SystemStatus,
    TrustBadge,
    WebhookActivity,
    WebhookRun,
)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _row_to_incident(row: dict, timeline: list[ActionEntry] | None = None) -> Incident:
    return Incident(
        id=row["id"],
        asset_urn=row["asset_urn"],
        asset_name=row.get("asset_name"),
        signal_type=row.get("signal_type"),
        summary=row.get("summary"),
        change_type=row.get("change_type"),
        confidence=row.get("confidence"),
        narrative=row.get("narrative"),
        root_cause_asset=row.get("root_cause_asset"),
        root_cause_column=row.get("root_cause_column"),
        tier=row.get("tier"),
        status=row["status"],
        resolved=row["resolved"],
        pr=row.get("pr"),
        cost_usd=row.get("cost_usd"),
        cost_basis=row.get("cost_basis"),
        downstream_count=row.get("downstream_count"),
        action_types=row.get("actions") or [],
        detected_at=_parse_dt(row["detected_at"]) or datetime.now(timezone.utc),
        closed_at=_parse_dt(row.get("closed_at")),
        updated_at=_parse_dt(row["updated_at"]) or datetime.now(timezone.utc),
        timeline=timeline or [],
    )


def _entry_to_action(entry) -> ActionEntry:
    return ActionEntry(
        action_type=_enum(entry.action_type),
        target=entry.target,
        status=entry.status,
        note=entry.note,
        reversible=entry.inverse is not None,
        applied_at=entry.applied_at,
    )


def _enum(value) -> str:
    return getattr(value, "value", str(value))


def _check_datahub() -> tuple[bool, Optional[str], str]:
    """A live, cheap ping — not just 'is a URL configured'. Short timeout so
    a dead GMS doesn't stall the whole systemStatus query."""
    import requests

    url = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
    try:
        resp = requests.get(f"{url}/config", timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            version = (
                data.get("versions", {})
                .get("acryldata/datahub", {})
                .get("version")
            )
            return True, version, url
    except Exception:
        pass
    return False, None, url


def _webhook_sources_enabled() -> tuple[list[str], int]:
    try:
        from agent.integrations.webhooks.config import WebhookConfig

        cfg = WebhookConfig.load()
        if not cfg.enabled:
            return [], 0
        sources = [s for s, sc in cfg.sources.items() if sc.enabled]
        return sources, cfg.sweep_interval_minutes
    except Exception:
        return [], 0


def _get_sweep_status() -> SweepStatus | None:
    """Read sweep scheduler state — only populated under ``python -m agent serve``."""
    try:
        from agent.integrations.webhooks import server as webhook_server

        scheduler = getattr(webhook_server, "_sweep_scheduler", None)
        if scheduler is None:
            return None
        st = scheduler.status
        return SweepStatus(
            interval_minutes=st.interval_minutes,
            is_running=st.is_running,
            last_run_at=st.last_run_at.isoformat() if st.last_run_at else None,
            next_run_at=st.next_run_at.isoformat() if st.next_run_at else None,
            last_error=st.last_error,
            total_runs=st.total_runs,
            total_errors=st.total_errors,
        )
    except Exception:
        return None

@strawberry.type
class Query:
    @strawberry.field
    def incidents(self, status: Optional[str] = None, limit: int = 50) -> list[Incident]:
        store: IncidentStore = shared_store()
        rows = store.list(status=status, limit=limit)
        return [_row_to_incident(r) for r in rows]

    @strawberry.field
    def incident(self, id: str) -> Optional[Incident]:
        store: IncidentStore = shared_store()
        row = store.get(id)
        if not row:
            return None
        entries = ActionJournal().for_incident(id)
        timeline = [_entry_to_action(e) for e in entries]
        return _row_to_incident(row, timeline=timeline)

    @strawberry.field
    def stats(self) -> Stats:
        store: IncidentStore = shared_store()
        s = store.stats()
        by_type = [
            ChangeTypeCount(change_type=k, count=v)
            for k, v in sorted(s["by_change_type"].items(), key=lambda kv: -kv[1])
        ]
        return Stats(
            total=s["total"],
            resolved=s["resolved"],
            open=s["open"],
            exposure_usd=s["exposure_usd"],
            mttr_minutes=s["mttr_minutes"],
            by_change_type=by_type,
        )

    @strawberry.field
    def trends(self, days: int = 30) -> list[DayPoint]:
        rows = shared_store().daily_series(days=days)
        return [
            DayPoint(
                day=r["day"], total=r["total"], resolved=r["resolved"],
                exposure_usd=r["exposure_usd"], mttr_minutes=r["mttr_minutes"],
            )
            for r in rows
        ]

    @strawberry.field
    def savings_digest(self) -> SavingsDigest:
        d = insights.savings_digest()
        return SavingsDigest(
            incidents=d["incidents"],
            actions_applied=d["actions_applied"],
            actions_simulated=d["actions_simulated"],
            actions_failed=d["actions_failed"],
            hours_saved=d["hours_saved"],
            shadow_mode=d["shadow_mode"],
            by_action=[ActionCount(action_type=a["action_type"], count=a["count"])
                       for a in d["by_action"]],
        )

    @strawberry.field
    def trust_badges(self) -> list[TrustBadge]:
        return [TrustBadge(**row) for row in insights.trust_badges()]

    @strawberry.field
    def runbooks(self) -> list[Runbook]:
        return [Runbook(**row) for row in insights.registered_runbooks()]

    @strawberry.field
    def journal(self, limit: int = 100) -> list[JournalEntry]:
        return [JournalEntry(**row) for row in insights.journal_entries(limit=limit)]

    @strawberry.field
    def webhook_activity(self) -> WebhookActivity:
        data = insights.webhook_activity()
        return WebhookActivity(
            attached=data["attached"],
            active=[WebhookRun(**r) for r in data["active"]],
            recent=[WebhookRun(**r) for r in data["recent"]],
        )

    @strawberry.field
    def system_status(self) -> SystemStatus:
        reachable, version, url = _check_datahub()
        sources, sweep = _webhook_sources_enabled()
        sweep_st = _get_sweep_status()
        return SystemStatus(
            datahub_reachable=reachable,
            datahub_version=version,
            datahub_url=url,
            slack_configured=bool(os.environ.get("SLACK_BOT_TOKEN")),
            slack_interactive_approvals=bool(os.environ.get("SLACK_APP_TOKEN")),
            pagerduty_configured=bool(os.environ.get("PAGERDUTY_ROUTING_KEY")),
            llm_configured=bool(os.environ.get("OPENROUTER_API_KEY")),
            llm_model=os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
            webhook_sources_enabled=sources,
            sweep_interval_minutes=sweep,
            sweep_status=sweep_st,
        )

    # --- Self-Maintaining APIs & Dependency Health ------------------------- #
    @strawberry.field
    def api_dependencies(self, force: bool = False) -> list[Dependency]:
        return [Dependency(**row) for row in api_health.list_dependencies(force=force)]

    @strawberry.field
    def active_advisories(self) -> list[Advisory]:
        rows = api_health.list_advisories()
        res = []
        for r in rows:
            usages = [AdvisoryUsage(**u) for u in r.get("usages", [])]
            r_copy = dict(r)
            r_copy["usages"] = usages
            res.append(Advisory(**r_copy))
        return res

    @strawberry.field
    def migration_history(self) -> list[Migration]:
        return [Migration(**row) for row in api_health.migration_history()]

    @strawberry.field
    def dependency_blast_radius(self, package: str) -> BlastRadius:
        data = api_health.dependency_blast_radius(package)
        downstream = [BlastRadiusNode(**d) for d in data.get("downstream_assets", [])]
        return BlastRadius(
            package=data["package"],
            files=data["files"],
            direct_assets=data["direct_assets"],
            downstream_assets=downstream,
            total_impacted=data["total_impacted"],
        )

    @strawberry.field
    def api_health_stats(self) -> ApiHealthStats:
        return ApiHealthStats(**api_health.api_health_stats())

    @strawberry.field
    def trigger_dependency_scan(self) -> DependencyScanResult:
        res = api_health.trigger_dependency_scan()
        return DependencyScanResult(
            scanned=res["scanned"],
            advisories_checked=res["advisories_checked"],
            incidents_found=res["incidents_found"],
            error=res.get("error"),
        )

    @strawberry.field
    def sync_registries(self) -> RegistrySyncResult:
        res = api_health.sync_registries()
        generated = [RegistrySyncItem(**g) for g in res.get("generated", [])]
        return RegistrySyncResult(
            success=res["success"],
            packages_checked=res["packages_checked"],
            advisories_generated=res["advisories_generated"],
            network_online=res["network_online"],
            error=res.get("error"),
            generated=generated,
        )

    @strawberry.field
    def remediate_advisory(self, advisory_id: str) -> RemediateAdvisoryResult:
        res = api_health.remediate_advisory(advisory_id)
        return RemediateAdvisoryResult(
            success=res["success"],
            incident_id=res.get("incident_id"),
            package=res.get("package"),
            pr=res.get("pr"),
            diff_path=res.get("diff_path"),
            diff_preview=res.get("diff_preview"),
            files_modified=res.get("files_modified", 0),
            error=res.get("error"),
        )


@strawberry.type
class Mutation:
    @strawberry.mutation
    def noop(self) -> bool:
        """Placeholder — Strawberry requires at least one mutation field."""
        return True
