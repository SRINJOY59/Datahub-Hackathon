"""The dashboard's write path — drills, rollbacks, and badge rescoring.

Everything else in api/ only reads. This module is the deliberate exception,
so it carries the safeguards the read side does not need:

  * every action is individually switchable in config/dashboard.yaml, and the
    whole module is off if that file is missing — a fresh checkout does not
    silently expose a write endpoint;
  * actions run on a background thread and return a job id, because a drill
    runs the full remediation loop and would otherwise hold an HTTP request
    open for minutes;
  * the work itself is delegated to the same code paths the CLI uses
    (FailureInjector, ActionJournal.undo_all, TrustScorer.score_and_publish)
    rather than reimplemented, so the dashboard cannot drift from the agent.

There is no authentication here. See config/dashboard.yaml for what that
means and when to turn it off.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import yaml

_CONFIG_PATH = Path("config/dashboard.yaml")


@dataclass
class ActionsConfig:
    enabled: bool = False
    allow_drill: bool = False
    allow_rollback: bool = False
    allow_rescore: bool = False

    @classmethod
    def load(cls) -> "ActionsConfig":
        if not _CONFIG_PATH.exists():
            return cls()  # absent config == everything off
        try:
            raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            return cls()
        actions = raw.get("actions") or {}
        if not isinstance(actions, dict):
            return cls()
        enabled = bool(actions.get("enabled", False))
        return cls(
            enabled=enabled,
            allow_drill=enabled and bool(actions.get("allow_drill", False)),
            allow_rollback=enabled and bool(actions.get("allow_rollback", False)),
            allow_rescore=enabled and bool(actions.get("allow_rescore", False)),
        )


@dataclass
class Job:
    id: str
    kind: str
    target: str
    status: str = "running"  # running | succeeded | failed
    log: list[str] = field(default_factory=list)
    error: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None

    def as_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "target": self.target,
            "status": self.status, "log": self.log, "error": self.error,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class JobRunner:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, target: str, work: Callable[[Job], None]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, target=target)
        with self._lock:
            self._jobs[job.id] = job

        def run() -> None:
            try:
                work(job)
                job.status = "succeeded"
            except Exception as exc:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                job.finished_at = datetime.now(timezone.utc)

        threading.Thread(target=run, daemon=True).start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self, limit: int = 20) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)
        return jobs[:limit]


runner = JobRunner()


# --- the work itself -------------------------------------------------------- #
def run_drill(scenario: str) -> Job:
    def work(job: Job) -> None:
        from dotenv import load_dotenv

        load_dotenv()
        from agent.llm import LLMClient
        from agent.orchestrator import SentinelAgent
        from agent.tools.mechanisms.composite import RealMechanisms
        from memory.base import get_memory

        llm = LLMClient()
        memory = get_memory()
        mechanisms = RealMechanisms(llm=llm, memory=memory)
        agent = SentinelAgent(mechanisms, llm=llm, memory=memory)

        job.log.append(f"injecting {scenario}")
        incident = mechanisms.inject_failure(scenario)
        if incident is None:
            raise RuntimeError(
                f"drill failed: the agent did not detect the incident "
                f"'{scenario}' was supposed to cause"
            )
        job.log.append(f"detected {incident.id}: {incident.signal_type.value}")
        outcome = agent.handle(incident)
        job.log.append(f"outcome: {outcome.status} (resolved={outcome.resolved})")

    return runner.submit("drill", scenario, work)


def run_rollback(incident_id: str) -> Job:
    def work(job: Job) -> None:
        from agent.journal import ActionJournal
        from agent.tools.mechanisms.composite import RealMechanisms

        mechanisms = RealMechanisms()
        entries = ActionJournal().applied_for_incident(incident_id)
        if not entries:
            raise RuntimeError(f"nothing applied for {incident_id} to roll back")
        job.log.append(f"{len(entries)} applied action(s) to withdraw")
        reverted, failed = mechanisms.rollback(incident_id, mutating_only=False)
        job.log.append(f"reverted {reverted}, failed {failed}")
        if failed:
            raise RuntimeError(f"{failed} action(s) could not be reverted")

    return runner.submit("rollback", incident_id, work)


def run_rescore() -> Job:
    def work(job: Job) -> None:
        import os

        from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig

        from agent.tools.graph.trust import TrustScorer
        from agent.tools.graph.urns import short_name

        gms = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
        graph = DataHubGraph(DataHubGraphConfig(server=gms))
        scorer = TrustScorer(gms_server=gms)
        urns = sorted(graph.get_urns_by_filter(entity_types=["dataset"],
                                               platform="dbt"))
        for urn in urns:
            score = scorer.score_and_publish(urn)
            job.log.append(f"{short_name(urn) or urn}: {score.grade} ({score.score})")

        from api import insights

        insights.trust_badges(force=True)  # refresh the cached read view

    return runner.submit("rescore", "all dbt datasets", work)


def available_scenarios() -> list[str]:
    try:
        from agent.tools.mechanisms.injector import FailureInjector

        return FailureInjector().available()
    except Exception:
        return []
