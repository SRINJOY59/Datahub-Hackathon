"""HTTP wiring for the actuation endpoints.

Each route re-reads the config on every request rather than caching it at
import time, so flipping an action off in config/dashboard.yaml takes effect
without a restart — the fastest way to shut a write path is the one that
doesn't require finding the process first.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api import actions

router = APIRouter(prefix="/actions")


def _require(flag: str) -> actions.ActionsConfig:
    cfg = actions.ActionsConfig.load()
    if not cfg.enabled:
        raise HTTPException(403, "Dashboard actions are disabled "
                                 "(config/dashboard.yaml: actions.enabled)")
    if not getattr(cfg, flag, False):
        raise HTTPException(403, f"This action is disabled "
                                 f"(config/dashboard.yaml: actions.{flag})")
    return cfg


@router.get("/config")
def get_config():
    cfg = actions.ActionsConfig.load()
    return {
        "enabled": cfg.enabled,
        "allowDrill": cfg.allow_drill,
        "allowRollback": cfg.allow_rollback,
        "allowRescore": cfg.allow_rescore,
        "scenarios": actions.available_scenarios(),
    }


@router.post("/drill/{scenario}")
def post_drill(scenario: str):
    _require("allow_drill")
    if scenario not in actions.available_scenarios():
        raise HTTPException(400, f"Unknown scenario '{scenario}'")
    return actions.run_drill(scenario).as_dict()


@router.get("/drill/{scenario}/stream")
def stream_drill(scenario: str):
    _require("allow_drill")
    if scenario not in actions.available_scenarios():
        raise HTTPException(400, f"Unknown scenario '{scenario}'")
    return StreamingResponse(
        actions.stream_drill_sync(scenario),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/rollback/{incident_id}")
def post_rollback(incident_id: str):
    _require("allow_rollback")
    return actions.run_rollback(incident_id).as_dict()


@router.post("/rescore")
def post_rescore():
    _require("allow_rescore")
    return actions.run_rescore().as_dict()


@router.get("/jobs")
def list_jobs():
    return {"jobs": [j.as_dict() for j in actions.runner.recent()]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = actions.runner.get(job_id)
    if not job:
        raise HTTPException(404, "No such job")
    return job.as_dict()
