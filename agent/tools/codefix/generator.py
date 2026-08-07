"""CodeFixTool — generates a real code fix and opens a PR (or writes a diff
locally when no GitHub token is set).

Flow: read the affected file -> ask the LLM for the fully-rewritten file ->
compute a unified diff locally with difflib (so the diff is always valid) ->
write it to examples/generated_fixes/ -> open a draft PR if configured.

This is the "apply the change, don't just announce it" step.

The tool takes a `FixRequest`: a file and an instruction. A vendor advisory is
one way to arrive at one, but not the only way — a leaked label is repaired by
removing a feature from the model's config, with no advisory anywhere in sight.
Keeping the request generic means an incident class earns a real code fix by
describing what needs changing, rather than by pretending to be a dependency
upgrade.
"""
from __future__ import annotations

import difflib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from agent.contracts import ContextBundle, Incident
from agent.llm import LLMClient

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXES_DIR = REPO_ROOT / "examples" / "generated_fixes"

_SYSTEM = ("You are a senior engineer applying a targeted change to one file. "
           "Return the COMPLETE updated file content only — no markdown fences, "
           "no prose. Change only what the instruction requires.")

NOTHING_TO_FIX = "no affected files found — nothing to fix"
NO_FIX_GENERATED = "could not generate a fix (LLM unavailable or no change)"


@dataclass
class FixRequest:
    """One file, and what needs to change about it."""
    file: str                  # repo-relative path
    instruction: str           # what to change and why
    title: str = "code fix"    # PR title / commit subject
    detail: str = ""           # extra context for the PR body


class CodeFixTool:
    def __init__(self, llm: Optional[LLMClient] = None,
                 github_token: Optional[str] = None,
                 github_repo: Optional[str] = None) -> None:
        self.llm = llm
        self.token = github_token or os.getenv("GITHUB_TOKEN") or ""
        self.repo = github_repo or os.getenv("GITHUB_REPO") or ""

    # ------------------------------------------------------------------ #
    def propose_fix(self, incident: Incident, context: ContextBundle,
                    root_cause: str) -> str:
        request = self._request_for(incident, root_cause)
        if request is None:
            return NOTHING_TO_FIX
        return self.apply_request(incident, request)

    def apply_request(self, incident: Incident, request: FixRequest) -> str:
        """Rewrite one file per the request, diff it, and open a PR if possible."""
        path = REPO_ROOT / request.file
        if not path.exists():
            return NOTHING_TO_FIX
        original = path.read_text(encoding="utf-8", errors="ignore")

        fixed = self._rewrite(request, original)
        if fixed is None or fixed.strip() == original.strip():
            return NO_FIX_GENERATED

        # Check the proposal in a place it cannot hurt anything before putting it
        # in front of a human. A confidently-worded fix that does not parse is
        # worse than no fix, because someone has to read it to find that out.
        if request.file.endswith(".py"):
            from agent.tools.warehouse.shadow import ShadowEnvironment

            verdict = ShadowEnvironment.verify_python(request.file, fixed)
            if not verdict.passed:
                return f"{NO_FIX_GENERATED}: {'; '.join(verdict.failures)}"
            request.detail = (request.detail + f"\n\nShadow check: {verdict.note}"
                              ).strip()

        diff = "".join(difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile=f"a/{request.file}", tofile=f"b/{request.file}",
        ))

        FIXES_DIR.mkdir(parents=True, exist_ok=True)
        diff_path = FIXES_DIR / f"{incident.id}.diff"
        diff_path.write_text(diff, encoding="utf-8")

        pr = (self._open_pr(incident, request, fixed)
              if self.token and self.repo else None)
        return pr or diff_path.relative_to(REPO_ROOT).as_posix()

    # ------------------------------------------------------------------ #
    def _request_for(self, incident: Incident,
                     root_cause: str) -> Optional[FixRequest]:
        """Derive a fix request from the incident, when one applies.

        Dependency advisories carry the affected file and the migration text.
        Other incident classes attach a `fix_request` to their evidence when they
        know what code needs changing; most attach nothing, because most
        incidents are repaired by moving data rather than by editing code.
        """
        evidence = incident.raw_evidence or {}

        explicit = evidence.get("fix_request")
        if isinstance(explicit, dict) and explicit.get("file"):
            return FixRequest(
                file=explicit["file"],
                instruction=explicit.get("instruction", root_cause),
                title=explicit.get("title", "code fix"),
                detail=explicit.get("detail", ""),
            )

        adv = evidence.get("advisory") or {}
        usages = evidence.get("usages") or []
        if adv and usages:
            return FixRequest(
                file=usages[0]["file"],
                instruction=(
                    f"Dependency change: {adv.get('package')} "
                    f"{adv.get('from_version')} -> {adv.get('to_version')}\n"
                    f"Breaking change: {adv.get('summary')}\n"
                    f"Migration required: {adv.get('migration')}"
                ),
                title=f"{adv.get('package')} {adv.get('to_version')} migration",
                detail=adv.get("migration", ""),
            )
        return None

    def _rewrite(self, request: FixRequest, content: str) -> Optional[str]:
        if not (self.llm and self.llm.available()):
            return None
        prompt = (
            f"File: {request.file}\n"
            f"{request.instruction}\n\n"
            f"Apply this change to the file and return the full updated content:\n\n"
            f"{content}"
        )
        try:
            out = self.llm.complete(prompt, system=_SYSTEM, max_tokens=2000)
        except Exception:
            return None
        return _strip_fences(out)

    def _open_pr(self, incident: Incident, request: FixRequest,
                 content: str) -> Optional[str]:
        try:
            from github import Github

            gh = Github(self.token)
            repo = gh.get_repo(self.repo)
            base = repo.default_branch
            branch = f"sentinel/{incident.id.lower()}"
            sha = repo.get_branch(base).commit.sha
            repo.create_git_ref(ref=f"refs/heads/{branch}", sha=sha)
            gh_file = repo.get_contents(request.file, ref=branch)
            repo.update_file(
                request.file, f"fix: {request.title}",
                content, gh_file.sha, branch=branch,
            )
            pr = repo.create_pull(
                title=f"[Sentinel] {request.title}",
                body=(f"Automated fix for {incident.id}.\n\n"
                      f"{request.detail or request.instruction}"),
                head=branch, base=base, draft=True,
            )
            return pr.html_url
        except Exception as e:
            # A token was configured, so silently writing a diff would let a
            # failed PR look like the intended outcome. Surface why it failed and
            # fall back to the diff, rather than pretending a PR was never wanted.
            print(f"  [fix      ] PR creation failed for {self.repo}: "
                  f"{type(e).__name__}: {e} — falling back to a local diff")
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
