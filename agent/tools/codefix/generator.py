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
        requests = self._requests_for(incident, root_cause)
        if not requests:
            return NOTHING_TO_FIX
        return self.apply_requests(incident, requests)

    def apply_request(self, incident: Incident, request: FixRequest) -> str:
        """Rewrite one file per the request, diff it, and open a PR if possible."""
        return self.apply_requests(incident, [request])

    def apply_requests(self, incident: Incident, requests: list[FixRequest]) -> str:
        """Rewrite all affected files, combine their diffs, and open a PR with all changes."""
        if not requests:
            return NOTHING_TO_FIX

        fixed_files: dict[str, tuple[str, str, FixRequest]] = {}  # file -> (original, fixed, request)
        diff_chunks: list[str] = []
        failures: list[str] = []

        for req in requests:
            path = REPO_ROOT / req.file
            if not path.exists():
                failures.append(f"{req.file}: file not found")
                continue
            original = path.read_text(encoding="utf-8", errors="ignore")

            fixed = self._rewrite(req, original)
            if fixed is None or fixed.strip() == original.strip():
                failures.append(f"{req.file}: no valid fix generated")
                continue

            if req.file.endswith(".py"):
                from agent.tools.warehouse.shadow import ShadowEnvironment

                verdict = ShadowEnvironment.verify_python(req.file, fixed)
                if not verdict.passed:
                    failures.append(f"{req.file}: shadow check failed ({'; '.join(verdict.failures)})")
                    continue
                req.detail = (req.detail + f"\n\nShadow check ({req.file}): {verdict.note}").strip()

            diff_chunk = "".join(difflib.unified_diff(
                original.splitlines(keepends=True),
                fixed.splitlines(keepends=True),
                fromfile=f"a/{req.file}", tofile=f"b/{req.file}",
            ))
            if diff_chunk:
                diff_chunks.append(diff_chunk)
                fixed_files[req.file] = (original, fixed, req)

        if not fixed_files:
            fail_msg = f": {'; '.join(failures)}" if failures else ""
            return f"{NO_FIX_GENERATED}{fail_msg}"

        combined_diff = "\n".join(diff_chunks)
        FIXES_DIR.mkdir(parents=True, exist_ok=True)
        diff_path = FIXES_DIR / f"{incident.id}.diff"
        diff_path.write_text(combined_diff, encoding="utf-8")

        main_title = requests[0].title if requests else "code fix"
        all_details = "\n\n".join(filter(None, [r.detail or r.instruction for r in requests]))

        pr = (self._open_multi_pr(incident, main_title, all_details, fixed_files)
              if self.token and self.repo else None)
        return pr or diff_path.relative_to(REPO_ROOT).as_posix()

    # ------------------------------------------------------------------ #
    def _requests_for(self, incident: Incident,
                      root_cause: str) -> list[FixRequest]:
        """Derive one or more fix requests from the incident evidence."""
        evidence = incident.raw_evidence or {}

        # 1. Check for explicit list of fix requests
        explicit_list = evidence.get("fix_requests")
        if isinstance(explicit_list, list) and explicit_list:
            reqs = []
            for item in explicit_list:
                if isinstance(item, dict) and item.get("file"):
                    reqs.append(FixRequest(
                        file=item["file"],
                        instruction=item.get("instruction", root_cause),
                        title=item.get("title", "code fix"),
                        detail=item.get("detail", ""),
                    ))
            if reqs:
                return reqs

        # 2. Check for single explicit fix request
        explicit = evidence.get("fix_request")
        if isinstance(explicit, dict) and explicit.get("file"):
            return [FixRequest(
                file=explicit["file"],
                instruction=explicit.get("instruction", root_cause),
                title=explicit.get("title", "code fix"),
                detail=explicit.get("detail", ""),
            )]

        # 3. Derive from advisory and all unique files in usages
        adv = evidence.get("advisory") or {}
        usages = evidence.get("usages") or []
        if adv and usages:
            # Collect unique files preserving order
            unique_files: list[str] = []
            for u in usages:
                f = u.get("file") if isinstance(u, dict) else getattr(u, "file", None)
                if f and f not in unique_files:
                    unique_files.append(f)

            instruction = (
                f"Dependency change: {adv.get('package')} "
                f"{adv.get('from_version')} -> {adv.get('to_version')}\n"
                f"Breaking change: {adv.get('summary')}\n"
                f"Migration required: {adv.get('migration')}"
            )
            title = f"{adv.get('package')} {adv.get('to_version')} migration"
            detail = adv.get("migration", "")

            return [
                FixRequest(
                    file=f,
                    instruction=instruction,
                    title=title,
                    detail=detail,
                )
                for f in unique_files
            ]

        return []

    def _request_for(self, incident: Incident,
                     root_cause: str) -> Optional[FixRequest]:
        reqs = self._requests_for(incident, root_cause)
        return reqs[0] if reqs else None

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

    def _open_multi_pr(self, incident: Incident, title: str, detail: str,
                       fixed_files: dict[str, tuple[str, str, FixRequest]]) -> Optional[str]:
        try:
            from github import Github

            gh = Github(self.token)
            repo = gh.get_repo(self.repo)
            base = repo.default_branch
            branch = f"sentinel/{incident.id.lower()}"
            sha = repo.get_branch(base).commit.sha
            repo.create_git_ref(ref=f"refs/heads/{branch}", sha=sha)

            for file_path, (_, content, req) in fixed_files.items():
                gh_file = repo.get_contents(file_path, ref=branch)
                repo.update_file(
                    file_path, f"fix: {req.title} ({file_path})",
                    content, gh_file.sha, branch=branch,
                )

            pr = repo.create_pull(
                title=f"[Sentinel] {title}",
                body=(f"Automated migration for {incident.id} touching {len(fixed_files)} file(s).\n\n"
                      f"{detail}"),
                head=branch, base=base, draft=True,
            )
            return pr.html_url
        except Exception as e:
            print(f"  [fix      ] PR creation failed for {self.repo}: "
                  f"{type(e).__name__}: {e} — falling back to local diff")
            return None

    def _open_pr(self, incident: Incident, request: FixRequest,
                 content: str) -> Optional[str]:
        return self._open_multi_pr(incident, request.title, request.detail or request.instruction,
                                   {request.file: ("", content, request)})


def _strip_fences(text: str) -> str:
    """Remove leading ```lang and trailing ``` markdown fences if present."""
    out = (text or "").strip()
    if out.startswith("```"):
        out = out.split("\n", 1)[1] if "\n" in out else ""
    out = out.rstrip()
    if out.endswith("```"):
        out = out[:-3].rstrip()
    return out + "\n"
