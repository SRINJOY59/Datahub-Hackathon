"""CodeFixTool — generates a real code fix for a dependency/API breaking change
and opens a PR (or writes a diff locally when no GitHub token is set).

Flow: read the affected file -> ask the LLM for the fully-migrated file ->
compute a unified diff locally with difflib (so the diff is always valid) ->
write it to examples/generated_fixes/ -> open a draft PR if configured.

This is the "apply the change, don't just announce it" step.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Optional

from agent.contracts import ContextBundle, Incident
from agent.llm import LLMClient

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXES_DIR = REPO_ROOT / "examples" / "generated_fixes"

_SYSTEM = ("You are a senior engineer applying a dependency/API migration. Return "
           "the COMPLETE updated file content only — no markdown fences, no prose.")


class CodeFixTool:
    def __init__(self, llm: Optional[LLMClient] = None,
                 github_token: Optional[str] = None,
                 github_repo: Optional[str] = None) -> None:
        self.llm = llm
        self.token = github_token or os.getenv("GITHUB_TOKEN") or ""
        self.repo = github_repo or os.getenv("GITHUB_REPO") or ""

    def propose_fix(self, incident: Incident, context: ContextBundle,
                    root_cause: str) -> str:
        adv = (incident.raw_evidence or {}).get("advisory", {})
        usages = (incident.raw_evidence or {}).get("usages", [])
        if not usages:
            return "no affected files found — nothing to fix"

        target = usages[0]["file"]  # primary affected file
        path = REPO_ROOT / target
        original = path.read_text(encoding="utf-8", errors="ignore")

        fixed = self._migrate(target, original, adv)
        if fixed is None or fixed.strip() == original.strip():
            return "could not generate a fix (LLM unavailable or no change)"

        diff = "".join(difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile=f"a/{target}", tofile=f"b/{target}",
        ))

        FIXES_DIR.mkdir(parents=True, exist_ok=True)
        diff_path = FIXES_DIR / f"{incident.id}.diff"
        diff_path.write_text(diff, encoding="utf-8")

        pr = self._open_pr(incident, target, fixed, adv) if self.token and self.repo else None
        return pr or diff_path.relative_to(REPO_ROOT).as_posix()

    # ------------------------------------------------------------------ #
    def _migrate(self, filename: str, content: str, adv: dict) -> Optional[str]:
        if not (self.llm and self.llm.available()):
            return None
        prompt = (
            f"File: {filename}\n"
            f"Dependency change: {adv.get('package')} {adv.get('from_version')} -> "
            f"{adv.get('to_version')}\n"
            f"Breaking change: {adv.get('summary')}\n"
            f"Migration required: {adv.get('migration')}\n\n"
            f"Apply the migration to this file and return the full updated content:\n\n"
            f"{content}"
        )
        try:
            out = self.llm.complete(prompt, system=_SYSTEM, max_tokens=2000)
        except Exception:
            return None
        return _strip_fences(out)

    def _open_pr(self, incident: Incident, filename: str, content: str,
                 adv: dict) -> Optional[str]:
        try:
            from github import Github

            gh = Github(self.token)
            repo = gh.get_repo(self.repo)
            base = repo.default_branch
            branch = f"sentinel/{incident.id.lower()}"
            sha = repo.get_branch(base).commit.sha
            repo.create_git_ref(ref=f"refs/heads/{branch}", sha=sha)
            gh_file = repo.get_contents(filename, ref=branch)
            repo.update_file(
                filename,
                f"fix: apply {adv.get('package')} {adv.get('to_version')} migration",
                content, gh_file.sha, branch=branch,
            )
            pr = repo.create_pull(
                title=f"[Sentinel] {adv.get('package')} {adv.get('to_version')} migration",
                body=f"Automated migration for {incident.id}.\n\n{adv.get('migration')}",
                head=branch, base=base, draft=True,
            )
            return pr.html_url
        except Exception:
            return None


def _strip_fences(text: str) -> str:
    """Remove leading ```lang and trailing ``` markdown fences if present."""
    out = (text or "").strip()
    if out.startswith("```"):
        out = out.split("\n", 1)[1] if "\n" in out else ""
    out = out.rstrip()
    if out.endswith("```"):
        out = out[:-3].rstrip()
    return out + "\n"
