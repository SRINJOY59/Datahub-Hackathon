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
from api import insights
from api.types import (
    ActionCount,
    ActionEntry,
    ChangeTypeCount,
    DayPoint,
    Incident,
    JournalEntry,
    Runbook,
    SavingsDigest,
    Stats,
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
        )
