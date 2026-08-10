"""RunQueue — thread pool for concurrent agent runs with dedup."""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from agent.integrations.webhooks.router import AgentRunRequest

_MAX_HISTORY = 100  # Cap completed runs to prevent unbounded memory growth.


@dataclass
class RunStatus:
    run_id: str
    asset_urn: str
    source: str
    status: str  # queued, running, completed, failed, skipped
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None


class RunQueue:
    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix="sentinel-run")
        self._active: dict[str, RunStatus] = {}
        self._lock = threading.Lock()
        self._history: list[RunStatus] = []

    def submit(self, request: AgentRunRequest, run_fn) -> RunStatus:
        with self._lock:
            for run in self._active.values():
                if run.asset_urn == request.asset_urn and run.status in ("queued", "running"):
                    return RunStatus(
                        run_id=run.run_id,
                        asset_urn=request.asset_urn,
                        source=request.source,
                        status="skipped",
                    )

            run_id = uuid.uuid4().hex[:12]
            status = RunStatus(
                run_id=run_id,
                asset_urn=request.asset_urn,
                source=request.source,
                status="queued",
            )
            self._active[run_id] = status

        self._pool.submit(self._execute, run_id, request, run_fn)
        return status

    def _execute(self, run_id: str, request: AgentRunRequest, run_fn) -> None:
        with self._lock:
            self._active[run_id].status = "running"
            self._active[run_id].started_at = datetime.now(timezone.utc)

        try:
            run_fn(request)
            with self._lock:
                self._active[run_id].status = "completed"
        except Exception as exc:
            with self._lock:
                self._active[run_id].status = "failed"
                self._active[run_id].error = str(exc)
        finally:
            with self._lock:
                self._active[run_id].finished_at = datetime.now(timezone.utc)
                self._history.append(self._active.pop(run_id))
                # Trim oldest entries so memory doesn't grow unboundedly.
                if len(self._history) > _MAX_HISTORY:
                    self._history = self._history[-_MAX_HISTORY:]

    def active_runs(self) -> list[RunStatus]:
        with self._lock:
            return list(self._active.values())

    def recent_runs(self, limit: int = 20) -> list[RunStatus]:
        with self._lock:
            return list(self._history[-limit:])

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)
