"""Read-side adapters over the agent's own modules.

Everything here reads what the loop already produces — trust scores, the
savings digest, registered runbooks, the action journal — and returns plain
dicts for the resolvers. Two rules shape it:

  * DataHub may be down. Every function that touches the graph degrades to an
    empty result instead of raising, because a dashboard panel that cannot
    load is a worse failure than a panel that says "nothing yet".
  * Scoring is not free. TrustScorer.score() makes several DataHub calls per
    asset, so the badge list is cached behind a short TTL rather than
    recomputed on every poll of every open browser tab.
"""
from __future__ import annotations

from typing import Any, Optional

from api.shared import TTLCache, gms_url

_trust_cache: TTLCache[list[dict]] = TTLCache(ttl_seconds=60.0)


def savings_digest() -> dict:
    from agent.reporting.digest import SavingsDigest

    try:
        d = SavingsDigest().build()
    except Exception:
        return {
            "incidents": 0, "actions_applied": 0, "actions_simulated": 0,
            "actions_failed": 0, "hours_saved": 0.0, "shadow_mode": False,
            "by_action": [],
        }
    return {
        "incidents": d.incidents,
        "actions_applied": d.actions_applied,
        "actions_simulated": d.actions_simulated,
        "actions_failed": d.actions_failed,
        "hours_saved": d.hours_saved,
        "shadow_mode": d.shadow_mode,
        "by_action": [{"action_type": k, "count": v} for k, v in
                      sorted(d.by_action.items(), key=lambda kv: -kv[1])],
    }


def journal_entries(limit: int = 100) -> list[dict]:
    from agent.journal import ActionJournal

    try:
        entries = ActionJournal().entries()
    except Exception:
        return []
    out = []
    for e in entries[-limit:][::-1]:  # newest first
        out.append({
            "action_type": getattr(e.action_type, "value", str(e.action_type)),
            "target": e.target,
            "status": e.status,
            "note": e.note,
            "incident_id": e.incident_id,
            "reversible": e.inverse is not None,
            "applied_at": e.applied_at.isoformat() if e.applied_at else None,
        })
    return out


def trust_badges(force: bool = False) -> list[dict]:
    """Live trust score per dbt dataset. Never publishes — this is the
    read-only view of what `python -m agent badges` would write."""
    if not force:
        cached = _trust_cache.get()
        if cached is not None:
            return cached

    try:
        from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig

        from agent.tools.graph.trust import TrustScorer
        from agent.tools.graph.urns import short_name

        gms = gms_url()
        graph = DataHubGraph(DataHubGraphConfig(server=gms))
        scorer = TrustScorer(gms_server=gms)
        urns = sorted(graph.get_urns_by_filter(entity_types=["dataset"],
                                               platform="dbt"))
    except Exception:
        return _trust_cache.get() or []

    rows: list[dict] = []
    for urn in urns:
        try:
            s = scorer.score(urn)
        except Exception:
            continue
        rows.append({
            "asset_urn": urn,
            "asset_name": short_name(urn) or urn,
            "score": s.score,
            "grade": s.grade,
            "failed_assertions": int(s.inputs.get("failed_assertions", 0) or 0),
            "open_incident": bool(s.inputs.get("open_incident", False)),
            "volume_shift": float(s.inputs.get("volume_shift", 0.0) or 0.0),
            "freshness_lag_hours": float(s.inputs.get("freshness_lag_hours", 0.0) or 0.0),
            "past_incidents": int(s.inputs.get("past_incidents", 0) or 0),
        })
    rows.sort(key=lambda r: r["score"])
    _trust_cache.set(rows)
    return rows


def registered_runbooks() -> list[dict]:
    """The AgentSkill entities Sentinel has published, read back from DataHub.

    Pairs each with how many post-mortems currently back it, so the page can
    show both what exists and what is close to earning one.
    """
    from agent.contracts import ChangeType

    try:
        from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
        from datahub.metadata.schema_classes import AgentSkillInfoClass

        from agent.knowledge.runbook import MIN_INCIDENTS, skill_urn

        graph = DataHubGraph(DataHubGraphConfig(server=gms_url()))
    except Exception:
        return []

    try:
        from agent.knowledge.runbook import RunbookSynthesizer

        grouped = RunbookSynthesizer().collect()
    except Exception:
        grouped = {}

    out: list[dict] = []
    for change_type in [c.value for c in ChangeType]:
        urn = skill_urn(change_type)
        info: Optional[Any] = None
        try:
            info = graph.get_aspect(urn, AgentSkillInfoClass)
        except Exception:
            info = None
        backing = len(grouped.get(change_type, []))
        if info is None and backing == 0:
            continue  # neither registered nor has any history — not interesting
        out.append({
            "change_type": change_type,
            "skill_urn": urn if info is not None else None,
            "registered": info is not None,
            "title": getattr(info, "name", None),
            "description": getattr(info, "description", None),
            "instructions": getattr(info, "instructions", None),
            "incidents_backing": backing,
            "incidents_needed": max(0, MIN_INCIDENTS - backing),
        })
    out.sort(key=lambda r: (not r["registered"], -r["incidents_backing"]))
    return out


def webhook_activity() -> dict:
    """Live view of the webhook RunQueue merged with persistent event history."""
    try:
        from agent.integrations.webhooks import server as webhook_server
        from agent.store.incidents import shared_store

        queue = getattr(webhook_server, "_queue", None)
        active_list = []
        recent_list = []

        if queue is not None:
            for r in queue.active_runs():
                active_list.append({
                    "run_id": r.run_id,
                    "asset_urn": r.asset_urn,
                    "source": r.source,
                    "status": r.status,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "error": r.error,
                })
            for r in reversed(queue.recent_runs(limit=25)):
                recent_list.append({
                    "run_id": r.run_id,
                    "asset_urn": r.asset_urn,
                    "source": r.source,
                    "status": r.status,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "error": r.error,
                })

        # Supplement with persisted event runs if in-memory queue is empty or fresh
        if len(recent_list) < 5:
            store = shared_store()
            for inc in store.list(limit=20):
                sig = str(inc.get("signal_type") or "webhook").lower()
                source_name = "github" if "code" in sig else "advisory" if "dep" in sig else "dbt" if "assert" in sig else "airflow" if "schema" in sig else "webhook"
                recent_list.append({
                    "run_id": inc.get("id"),
                    "asset_urn": inc.get("asset_urn") or "urn:li:dataset:unknown",
                    "source": source_name,
                    "status": "completed" if inc.get("resolved") else inc.get("status") or "completed",
                    "started_at": inc.get("detected_at"),
                    "finished_at": inc.get("closed_at") or inc.get("updated_at"),
                    "error": None,
                })

        return {
            "attached": True,
            "active": active_list,
            "recent": recent_list[:30],
        }
    except Exception:
        return {"attached": True, "active": [], "recent": []}
