"""Actuator: stop a downstream job from consuming known-bad data.

Real systems pause an Airflow DAG or a Dagster sensor. Here the consumer is the
scoring job, so the breaker is a file it checks before running: with a breaker
open, `python -m ml.score` refuses to score and says why. That is a genuine
effect on the system rather than a log line claiming one.

The breaker records which incident opened it, so a human finding a paused job
can trace it back rather than guessing whether it is safe to clear.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent.contracts import ActionRecord, ActionType
from agent.registry import actuator
from agent.tools.actuators.base import BaseActuator

REPO_ROOT = Path(__file__).resolve().parents[3]
BREAKERS_DIR = REPO_ROOT / ".sentinel" / "breakers"


def breaker_path(job: str) -> Path:
    return BREAKERS_DIR / f"{job}.json"


def is_paused(job: str) -> dict | None:
    """Read an open breaker, if there is one. Used by ml/score.py."""
    path = breaker_path(job)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"job": job, "reason": "unreadable breaker file"}


def clear_all() -> int:
    """Remove every breaker — used when resetting the pipeline."""
    if not BREAKERS_DIR.exists():
        return 0
    files = list(BREAKERS_DIR.glob("*.json"))
    for f in files:
        f.unlink()
    return len(files)


@actuator
class PauseJobActuator(BaseActuator):
    name = "pause_job"
    action_type = ActionType.PAUSE_JOB

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        pass

    def _apply(self, action: ActionRecord) -> ActionRecord:
        job = action.params.get("job") or _job_from(action.target)
        path = breaker_path(job)
        already_open = path.exists()

        if not already_open:
            BREAKERS_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "job": job,
                "incident_id": action.incident_id,
                "reason": action.params.get("reason") or action.note or "open incident",
                "opened_at": datetime.now(timezone.utc).isoformat(),
            }, indent=2), encoding="utf-8")

        action.note = (action.note + (f" | breaker open on {job}" if not already_open
                                      else f" | {job} was already paused")).strip(" |")
        return ActionRecord(
            action_type=self.action_type,
            target=action.target,
            params={"job": job, "resume": True, "was_open": already_open},
            note=f"resume {job}",
            incident_id=action.incident_id,
        )

    def _revert(self, inverse: ActionRecord) -> bool:
        if inverse.params.get("was_open"):
            return True  # someone else paused it; not ours to resume
        path = breaker_path(inverse.params.get("job", ""))
        if path.exists():
            path.unlink()
        return True


def _job_from(target: str) -> str:
    """Fall back to the last identifiable segment of a urn."""
    if "," in target:
        return target.split(",")[1]
    return target or "unknown_job"
