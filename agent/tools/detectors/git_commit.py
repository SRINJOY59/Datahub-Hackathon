"""Detector: an unreviewed commit to a pipeline source file is a signal.

The agent already root-causes a *data* incident back to the commit that caused it
(Drift Attribution). This runs the same machinery forward: a commit touching a
file that produces a DataHub asset is raised *as* an incident, before its effect
shows up in the data — the earliest a code change can possibly be caught.

State is a single acknowledged sha in .sentinel/code_baseline.json: the last
commit the agent has accepted as reviewed. Commits after it that touch a pipeline
source are unreviewed; everything up to it is quiet. The first run adopts the
current HEAD, so a fresh repo does not raise every commit in its history.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent.contracts import Incident, SignalType
from agent.registry import detector
from agent.tools.code.git_history import GitHistory
from memory.codebase import shared_codebase

_BASELINE = Path(__file__).resolve().parents[3] / ".sentinel" / "code_baseline.json"


def acknowledged_sha() -> Optional[str]:
    try:
        return json.loads(_BASELINE.read_text(encoding="utf-8")).get("sha")
    except (OSError, ValueError):
        return None


def acknowledge(sha: str) -> None:
    """Mark commits up to `sha` as reviewed."""
    _BASELINE.parent.mkdir(parents=True, exist_ok=True)
    _BASELINE.write_text(json.dumps({"sha": sha}), encoding="utf-8")


def clear_acknowledged() -> None:
    _BASELINE.unlink(missing_ok=True)


@detector
class GitCommitDetector:
    name = "git_commits"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.git = GitHistory()
        self.codebase = shared_codebase()

    def detect(self) -> list[Incident]:
        if not self.git.available():
            return []
        head = self.git.head_sha()
        if not head:
            return []

        base = acknowledged_sha()
        if base is None:
            acknowledge(head)   # first sight of the repo is the known-good line
            return []
        if base == head:
            return []

        pipeline = set(self.codebase.pipeline_source_files())
        incidents: list[Incident] = []
        seen: set[str] = set()
        for commit in self.git.commits_since(base, list(pipeline), limit=20):
            touched = [f for f in self.git.files_changed_in(commit.sha) if f in pipeline]
            for rel in touched:
                asset = self.codebase.producer_of(rel)
                if not asset or asset in seen:
                    continue
                seen.add(asset)
                incidents.append(Incident(
                    id=f"COMMIT-{commit.sha}",
                    asset_urn=asset,
                    signal_type=SignalType.CODE_CHANGE,
                    detected_at=datetime.now(timezone.utc),
                    summary=(f"unreviewed commit {commit.sha} by {commit.author} "
                             f"touched {rel}: {commit.subject}"),
                    raw_evidence={"commit": {"sha": commit.sha,
                                             "author": commit.author,
                                             "date": commit.date,
                                             "subject": commit.subject},
                                  "file": rel},
                ))
        return incidents
