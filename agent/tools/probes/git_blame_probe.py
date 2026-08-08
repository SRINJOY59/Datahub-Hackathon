"""Probe: which change caused this.

Root-causing to "raw_transactions.amount shifted 100x" is where most tooling
stops, and it leaves the on-call with the real work still to do. What they need
is the commit: who changed which file, when, and why they said they were doing
it.

The link already exists in the codebase index — `CodebaseMemory` knows which
source file produces which DataHub asset, because that is how a dependency
upgrade gets traced to the model it breaks. Reading that map backwards turns an
asset into a file, and git turns a file into a commit and an author.

Evidence here deliberately carries no `column`, so it informs the narrative
without competing to be the root cause: the anomaly is still what the profiler
measured, this just says who moved it.
"""
from __future__ import annotations

from agent.contracts import ContextBundle, Evidence, Incident
from agent.registry import probe
from agent.tools.code.git_history import GitHistory
from agent.tools.graph.urns import is_dataset
from memory.codebase import shared_codebase

# Any incident whose cause could plausibly be someone changing the pipeline.
_ATTRIBUTABLE = {
    "assertion_failure", "schema_change", "freshness", "model_drift",
    "volume_anomaly", "label_leakage", "training_regression",
    "training_serving_skew", "code_change",
}

MAX_COMMITS = 3
RECENT_WINDOW = "30 days ago"

# The code behind a model, for incidents whose urn no dbt file produces.
ML_TRAIN, ML_SCORE, ML_CONFIG = "ml/train.py", "ml/score.py", "ml/config.py"


@probe
class GitBlameProbe:
    name = "git_blame"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.git = GitHistory()
        self.codebase = shared_codebase()

    def applies_to(self, incident: Incident) -> bool:
        return incident.signal_type.value in _ATTRIBUTABLE

    def investigate(self, incident: Incident, context: ContextBundle) -> list[Evidence]:
        if not self.git.available():
            return []

        files = self._suspect_files(incident, context)
        if not files:
            return []

        evidence: list[Evidence] = []
        for rel_path in files[:MAX_COMMITS]:
            commit = self.git.last_commit_for(rel_path)
            if commit is None:
                continue
            evidence.append(Evidence(
                probe=self.name,
                kind="code_attribution",
                summary=(f"{rel_path} was last changed by {commit.author} on "
                         f"{commit.date[:10]} ({commit.sha}): {commit.subject}"),
                data={"file": rel_path, "sha": commit.sha, "author": commit.author,
                      "date": commit.date, "subject": commit.subject},
                confidence="medium",
            ))

        recent = self.git.recent_commits(files, limit=MAX_COMMITS,
                                         since=RECENT_WINDOW)
        if recent:
            evidence.append(Evidence(
                probe=self.name,
                kind="recent_changes",
                summary=("changes to the affected pipeline code in the last 30 days: "
                         + "; ".join(c.summary() for c in recent)),
                data={"commits": [c.__dict__ for c in recent]},
                confidence="medium",
            ))
        return evidence

    # ------------------------------------------------------------------ #
    def _suspect_files(self, incident: Incident,
                       context: ContextBundle) -> list[str]:
        """Source files that produce the incident's asset or anything upstream of
        it. A break shows up downstream of wherever it was introduced, so the
        upstream files are the ones worth blaming."""
        urns = [incident.asset_urn, *(n.urn for n in context.upstream)]
        producers = self.codebase.source_files()

        files: list[str] = []
        for urn in urns:
            for rel_path, produced in producers.items():
                if produced == urn and rel_path not in files:
                    files.append(rel_path)

        # A model incident carries an mlModel urn, which no dbt file produces, so
        # fall back to the code that trains, configures and serves it.
        if not files and not is_dataset(incident.asset_urn):
            files = [ML_TRAIN, ML_SCORE, ML_CONFIG]
        return files
