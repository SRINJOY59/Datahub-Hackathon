"""Code-change incident: an unreviewed commit touches a pipeline source file.

No data is corrupted and no git history is rewritten. The scenario simply moves
the agent's "last reviewed commit" marker back to the parent of the most recent
commit that touched a pipeline source — so that real commit now looks unreviewed.
The detector then raises it as an incident, attributing the real author and sha.
cleanup() clears the marker, so a reset re-adopts the current HEAD as reviewed.
"""
from __future__ import annotations

from scenarios.base import BaseScenario, Expectation


class RiskyCommitScenario(BaseScenario):
    name = "risky_commit"
    description = "An unreviewed commit touches a pipeline source file"

    expectation = Expectation(
        signal_type="code_change",
        change_type="code_change",
        actions=["tag_asset"],
        checks_pass_after_act=False,   # a human's commit is contained, not reverted
        trips_dbt_tests=False,         # nothing in the warehouse changed
        note="Detected from git history; contained (downstream flagged, author paged).",
    )

    def apply(self, reingest_after: bool = True) -> None:
        from agent.tools.code.git_history import GitHistory
        from agent.tools.detectors.git_commit import acknowledge
        from memory.codebase import shared_codebase

        git = GitHistory()
        if not git.available():
            print(f"[{self.name}] not a git repo — nothing to stage")
            return

        pipeline = shared_codebase().pipeline_source_files()
        recent = git.commits_since("HEAD~50", pipeline, limit=1) or \
            git.recent_commits(pipeline, limit=1)
        if not recent:
            print(f"[{self.name}] no commit in history touches a pipeline source")
            return

        commit = recent[0]
        parent = git.parent_sha(commit.sha)
        if not parent:
            print(f"[{self.name}] {commit.sha} is the root commit — cannot stage it")
            return

        acknowledge(parent)
        print(f"[{self.name}] treating commit {commit.sha} by {commit.author} "
              f"('{commit.subject}') as unreviewed "
              f"(reviewed marker set to its parent {parent})")
        print(f"\n[{self.name}] done. Run `python -m agent` to detect.")

    def cleanup(self) -> None:
        from agent.tools.detectors.git_commit import clear_acknowledged

        clear_acknowledged()
