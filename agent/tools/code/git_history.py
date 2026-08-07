"""Git history, for attributing a data change to the commit that caused it.

Root-causing to "raw_transactions.amount shifted 100x" is useful. Root-causing to
"commit 4f2a by Jordan, 'switch upstream feed to cents', touching
stg_transactions.sql" is what a human actually needs to fix it.

Read-only by construction: this module only ever runs `git log`, `git blame`, and
`git show`. Nothing here mutates the repository.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_SEP = "\x1f"  # unit separator — safe inside a --format string
_LOG_FORMAT = _SEP.join(["%h", "%an", "%aI", "%s"])


@dataclass
class Commit:
    sha: str
    author: str
    date: str      # ISO8601
    subject: str
    file: str = ""

    def summary(self) -> str:
        where = f" ({self.file})" if self.file else ""
        return f"{self.sha} by {self.author} on {self.date[:10]}: {self.subject}{where}"


class GitHistory:
    def __init__(self, repo_root: Path | str = REPO_ROOT) -> None:
        self.root = Path(repo_root)

    # ------------------------------------------------------------------ #
    def _git(self, args: list[str]) -> str:
        """Run a git command, returning stdout. Returns '' on any failure — a
        missing git binary or a non-repo directory is not worth an exception
        here, it just means no attribution evidence."""
        try:
            proc = subprocess.run(
                ["git", *args], cwd=str(self.root),
                capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return proc.stdout if proc.returncode == 0 else ""

    def available(self) -> bool:
        return bool(self._git(["rev-parse", "--is-inside-work-tree"]).strip())

    # ------------------------------------------------------------------ #
    def last_commit_for(self, rel_path: str) -> Commit | None:
        """The most recent commit touching one file."""
        out = self._git(["log", "-1", f"--format={_LOG_FORMAT}", "--", rel_path])
        commits = _parse_log(out, rel_path)
        return commits[0] if commits else None

    def commits_for(self, rel_path: str, limit: int = 5,
                    since: str | None = None) -> list[Commit]:
        args = ["log", f"-{limit}", f"--format={_LOG_FORMAT}"]
        if since:
            args.append(f"--since={since}")
        args += ["--", rel_path]
        return _parse_log(self._git(args), rel_path)

    def recent_commits(self, paths: list[str], limit: int = 10,
                       since: str | None = None) -> list[Commit]:
        """Recent commits across several files — used to find which of the
        pipeline's source files changed around the time an incident appeared."""
        args = ["log", f"-{limit}", f"--format={_LOG_FORMAT}"]
        if since:
            args.append(f"--since={since}")
        if paths:
            args += ["--", *paths]
        return _parse_log(self._git(args))

    def blame_line(self, rel_path: str, line_no: int) -> Commit | None:
        """Who last changed one specific line."""
        out = self._git([
            "blame", "-L", f"{line_no},{line_no}", "--porcelain", "--", rel_path,
        ])
        if not out:
            return None
        sha = out.split("\n", 1)[0].split(" ")[0][:9]
        author = _porcelain_field(out, "author")
        date = _porcelain_field(out, "author-time")
        subject = _porcelain_field(out, "summary")
        return Commit(sha=sha, author=author or "unknown",
                      date=date or "", subject=subject or "", file=rel_path)

    def files_changed_in(self, sha: str) -> list[str]:
        out = self._git(["show", "--name-only", "--format=", sha])
        return [line.strip() for line in out.splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
def _parse_log(output: str, rel_path: str = "") -> list[Commit]:
    commits: list[Commit] = []
    for line in (output or "").splitlines():
        parts = line.split(_SEP)
        if len(parts) != 4:
            continue
        sha, author, date, subject = parts
        commits.append(Commit(sha=sha, author=author, date=date,
                              subject=subject, file=rel_path))
    return commits


def _porcelain_field(blame_output: str, key: str) -> str:
    for line in blame_output.splitlines():
        if line.startswith(key + " "):
            return line[len(key) + 1:].strip()
    return ""
