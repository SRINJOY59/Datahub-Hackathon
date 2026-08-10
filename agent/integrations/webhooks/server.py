"""HTTP server for receiving webhooks — the entry point for event-driven runs.

Uses FastAPI + uvicorn. Single endpoint per source:
    POST /webhook/dbt
    POST /webhook/airflow
    POST /webhook/github
    POST /webhook/generic

Each request is HMAC-verified, parsed, and queued as an async agent run.

The sweep scheduler is exposed as a module-level ``_sweep_scheduler`` so
the GraphQL resolvers can read its state without a dependency on the serve
command's local scope.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel

from agent.integrations.webhooks.config import WebhookConfig
from agent.integrations.webhooks.queue import RunQueue
from agent.integrations.webhooks.router import AgentRunRequest, EventRouter
from agent.integrations.webhooks.sweep import SweepScheduler

logger = logging.getLogger("sentinel.webhooks")

app = FastAPI(title="Sentinel Webhook Server", version="0.1.0")

_config: Optional[WebhookConfig] = None
_router: Optional[EventRouter] = None
_queue: Optional[RunQueue] = None
_run_fn = None
_sweep_scheduler: Optional[SweepScheduler] = None


# ------------------------------------------------------------------ #
# Response models — replace hand-built JSON strings
# ------------------------------------------------------------------ #
class WebhookAccepted(BaseModel):
    status: str
    run_id: str
    asset_urn: str


class WebhookIgnored(BaseModel):
    status: str = "ignored"
    reason: str = "no matching asset mapping"


# ------------------------------------------------------------------ #
# Configuration
# ------------------------------------------------------------------ #
def configure(config: WebhookConfig, run_fn) -> None:
    """Wire up the server with its config, event router, and run queue."""
    global _config, _router, _queue, _run_fn
    _config = config
    _router = EventRouter(config)
    _queue = RunQueue(max_workers=config.server.workers)
    _run_fn = run_fn


def attach_sweep(scheduler: SweepScheduler) -> None:
    """Expose the sweep scheduler to the module for the GraphQL resolver."""
    global _sweep_scheduler
    _sweep_scheduler = scheduler


def _verify_signature(source: str, body: bytes,
                      signature: str | None) -> bool:
    """HMAC-SHA256 verification. No secret configured → pass-through."""
    secret = _config.secret_for(source) if _config else None
    if not secret:
        return True
    if not signature:
        return False

    sig = signature.removeprefix("sha256=")
    expected = hmac.new(
        secret.encode(), body, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig, expected)


# ------------------------------------------------------------------ #
# Webhook endpoint
# ------------------------------------------------------------------ #
@app.post("/webhook/{source}")
async def receive_webhook(
    source: str,
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_dbt_signature: str | None = Header(None),
):
    if not _config or not _router or not _queue or not _run_fn:
        raise HTTPException(503, "Webhook server not configured")

    src_cfg = _config.sources.get(source)
    if not src_cfg or not src_cfg.enabled:
        raise HTTPException(404, f"Source '{source}' not configured or disabled")

    body = await request.body()

    sig = x_hub_signature_256 or x_dbt_signature
    if not _verify_signature(source, body, sig):
        raise HTTPException(401, "Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    run_request = _router.route(source, payload)
    if not run_request:
        logger.info("webhook from %s ignored — no matching asset mapping", source)
        return WebhookIgnored()

    status = _queue.submit(run_request, _run_fn)
    logger.info("webhook from %s → %s (run_id=%s, status=%s)",
                source, status.asset_urn, status.run_id, status.status)

    return Response(
        content=WebhookAccepted(
            status=status.status,
            run_id=status.run_id,
            asset_urn=status.asset_urn,
        ).model_dump_json(),
        status_code=202 if status.status != "skipped" else 200,
        media_type="application/json",
    )


# ------------------------------------------------------------------ #
# Health + runs + sweep endpoints
# ------------------------------------------------------------------ #
@app.get("/health")
async def health():
    active = _queue.active_runs() if _queue else []
    return {
        "status": "ok",
        "active_runs": len(active),
    }


@app.get("/runs")
async def list_runs():
    if not _queue:
        return {"active": [], "recent": []}
    return {
        "active": [
            {"run_id": r.run_id, "asset_urn": r.asset_urn,
             "source": r.source, "status": r.status}
            for r in _queue.active_runs()
        ],
        "recent": [
            {"run_id": r.run_id, "asset_urn": r.asset_urn,
             "source": r.source, "status": r.status,
             "error": r.error}
            for r in _queue.recent_runs()
        ],
    }


@app.get("/sweep/status")
async def sweep_status():
    """Observable sweep scheduler state for dashboards and SRE tooling."""
    if not _sweep_scheduler:
        return {"configured": False}
    return {"configured": True, **_sweep_scheduler.status.as_dict()}


@app.post("/sweep/trigger")
async def sweep_trigger():
    """Trigger an immediate out-of-schedule sweep from the dashboard or CLI."""
    if not _sweep_scheduler:
        raise HTTPException(404, "Sweep scheduler not configured")
    result = _sweep_scheduler.run_now()
    if not result.get("triggered"):
        raise HTTPException(409, result.get("error", "Could not trigger sweep"))
    return result
