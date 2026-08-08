"""HTTP server for receiving webhooks — the entry point for event-driven runs.

Uses FastAPI + uvicorn. Single endpoint per source:
    POST /webhook/dbt
    POST /webhook/airflow
    POST /webhook/github
    POST /webhook/generic

Each request is HMAC-verified, parsed, and queued as an async agent run.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response

from agent.integrations.webhooks.config import WebhookConfig
from agent.integrations.webhooks.queue import RunQueue
from agent.integrations.webhooks.router import AgentRunRequest, EventRouter

app = FastAPI(title="Sentinel Webhook Server", version="0.1.0")

_config: Optional[WebhookConfig] = None
_router: Optional[EventRouter] = None
_queue: Optional[RunQueue] = None
_run_fn = None


def configure(config: WebhookConfig, run_fn) -> None:
    global _config, _router, _queue, _run_fn
    _config = config
    _router = EventRouter(config)
    _queue = RunQueue(max_workers=config.server.workers)
    _run_fn = run_fn


def _verify_signature(source: str, body: bytes,
                      signature: str | None) -> bool:
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
        return {"status": "ignored", "reason": "no matching asset mapping"}

    status = _queue.submit(run_request, _run_fn)

    return Response(
        content=f'{{"status": "{status.status}", "run_id": "{status.run_id}", '
                f'"asset_urn": "{status.asset_urn}"}}',
        status_code=202 if status.status != "skipped" else 200,
        media_type="application/json",
    )


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
