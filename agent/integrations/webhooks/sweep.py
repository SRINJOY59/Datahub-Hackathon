"""SweepScheduler — APScheduler-backed periodic agent sweeps.

Replaces the raw ``time.sleep()`` daemon thread that was in agent/__main__.py
with a proper scheduled task that has:

  * observable state (last run, next run, is running, error count);
  * jitter (±10%) to avoid thundering herd across instances;
  * graceful start/stop;
  * on-demand trigger (``run_now()``).

Uses APScheduler 3.x ``BackgroundScheduler`` with an ``IntervalTrigger``.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("sentinel.sweep")

_SWEEP_JOB_ID = "sentinel_periodic_sweep"


@dataclass
class SweepStatus:
    """Observable state of the sweep scheduler, exposed via the API."""
    interval_minutes: int = 0
    is_running: bool = False
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    last_error: Optional[str] = None
    total_runs: int = 0
    total_errors: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "interval_minutes": self.interval_minutes,
            "is_running": self.is_running,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "last_error": self.last_error,
            "total_runs": self.total_runs,
            "total_errors": self.total_errors,
        }


class SweepScheduler:
    """Manages periodic agent sweeps using APScheduler.

    Usage::

        scheduler = SweepScheduler()
        scheduler.start(interval_minutes=30, run_fn=agent.run)
        # ... later ...
        scheduler.stop()
    """

    def __init__(self) -> None:
        self._scheduler: Optional[BackgroundScheduler] = None
        self._run_fn: Optional[Callable[[], None]] = None
        self._status = SweepStatus()
        self._lock = threading.Lock()

    @property
    def status(self) -> SweepStatus:
        """Return a snapshot of the current sweep state."""
        # Refresh next_run_at from the scheduler if alive.
        if self._scheduler and self._scheduler.running:
            job = self._scheduler.get_job(_SWEEP_JOB_ID)
            if job and job.next_run_time:
                self._status.next_run_at = job.next_run_time
        return self._status

    def start(self, interval_minutes: int, run_fn: Callable[[], None]) -> None:
        """Start the periodic sweep.  Idempotent — calling twice is safe."""
        if self._scheduler and self._scheduler.running:
            logger.info("sweep scheduler already running — ignoring duplicate start")
            return

        self._run_fn = run_fn
        self._status.interval_minutes = interval_minutes

        self._scheduler = BackgroundScheduler(daemon=True)
        self._scheduler.add_listener(self._on_job_event,
                                     EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

        # ±10 % jitter keeps multiple instances from sweeping in lockstep.
        jitter = max(1, int(interval_minutes * 60 * 0.1))
        trigger = IntervalTrigger(minutes=interval_minutes, jitter=jitter)

        self._scheduler.add_job(
            self._execute_sweep,
            trigger=trigger,
            id=_SWEEP_JOB_ID,
            name="Sentinel periodic sweep",
            replace_existing=True,
        )

        self._scheduler.start()
        job = self._scheduler.get_job(_SWEEP_JOB_ID)
        if job and job.next_run_time:
            self._status.next_run_at = job.next_run_time
        logger.info("sweep scheduler started — interval %dm, jitter ±%ds",
                     interval_minutes, jitter)

    def stop(self) -> None:
        """Shut down the scheduler gracefully."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("sweep scheduler stopped")

    def run_now(self) -> dict[str, Any]:
        """Trigger an immediate out-of-schedule sweep.

        Returns a status dict suitable for an API response.
        """
        if not self._run_fn:
            return {"triggered": False, "error": "sweep not configured"}
        if self._status.is_running:
            return {"triggered": False, "error": "sweep already in progress"}

        # Run on a separate thread so the HTTP request isn't blocked.
        def _go():
            self._execute_sweep()

        threading.Thread(target=_go, daemon=True, name="sweep-manual").start()
        return {"triggered": True}

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _execute_sweep(self) -> None:
        """The actual sweep work — guarded by a lock so overlapping runs
        are impossible, and errors are captured rather than propagated."""
        with self._lock:
            if self._status.is_running:
                logger.warning("sweep already in progress — skipping")
                return
            self._status.is_running = True

        logger.info("[sweep] periodic sweep starting")
        try:
            if self._run_fn:
                self._run_fn()
            self._status.last_error = None
        except Exception as exc:
            self._status.last_error = f"{type(exc).__name__}: {exc}"
            self._status.total_errors += 1
            logger.exception("[sweep] error during periodic sweep")
        finally:
            self._status.is_running = False
            self._status.last_run_at = datetime.now(timezone.utc)
            self._status.total_runs += 1

    def _on_job_event(self, event) -> None:
        """APScheduler listener — update next_run_at after each execution."""
        if self._scheduler and self._scheduler.running:
            job = self._scheduler.get_job(_SWEEP_JOB_ID)
            if job and job.next_run_time:
                self._status.next_run_at = job.next_run_time
