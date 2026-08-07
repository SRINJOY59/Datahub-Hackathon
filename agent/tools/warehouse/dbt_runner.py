"""dbt invocation, in one place.

dbt runs in a subprocess rather than in-process: DuckDB allows a single writer,
and an in-process connection held open by the agent would deadlock against dbt's
own. Every caller in the repo goes through here so that discipline is enforced
once.

`test()` parses target/run_results.json rather than trusting the exit code, so
the validation gate can name the assertions that failed instead of only knowing
that something did.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DBT_DIR = REPO_ROOT / "pipeline" / "dbt"
RUN_RESULTS = DBT_DIR / "target" / "run_results.json"

_DBT_EXE = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")

_PASS_STATUSES = {"pass", "success"}


@dataclass
class DbtResult:
    """Outcome of one dbt invocation."""
    ok: bool
    command: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    returncode: int = 0

    @property
    def total(self) -> int:
        return len(self.passed) + len(self.failed)


class DbtRunner:
    def __init__(self, dbt_dir: Path | str = DBT_DIR,
                 dbt_exe: Path | str = _DBT_EXE) -> None:
        self.dbt_dir = Path(dbt_dir)
        self.dbt_exe = Path(dbt_exe)

    # ------------------------------------------------------------------ #
    def invoke(self, args: list[str], quiet: bool = False) -> DbtResult:
        """Run dbt with the project's profile/project dirs. Returns exit status
        only — use test() when you need per-assertion detail."""
        cmd = [str(self.dbt_exe), *args,
               "--profiles-dir", str(self.dbt_dir),
               "--project-dir", str(self.dbt_dir)]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.run(
            cmd, cwd=str(self.dbt_dir), env=env,
            capture_output=quiet, text=True,
        )
        return DbtResult(ok=proc.returncode == 0, command=cmd,
                         returncode=proc.returncode)

    def run(self, select: str | None = None, quiet: bool = False) -> DbtResult:
        args = ["run"] + (["--select", select] if select else [])
        return self.invoke(args, quiet=quiet)

    def seed(self, full_refresh: bool = True, quiet: bool = False) -> DbtResult:
        args = ["seed"] + (["--full-refresh"] if full_refresh else [])
        return self.invoke(args, quiet=quiet)

    def build(self, quiet: bool = False) -> DbtResult:
        return self.invoke(["build"], quiet=quiet)

    def test(self, select: str | None = None, quiet: bool = True) -> DbtResult:
        """Run assertions and report which ones passed or failed by name.

        dbt exits non-zero when any test fails, so the exit code alone can't
        distinguish "3 assertions failed" from "dbt itself blew up" — hence
        reading run_results.json.
        """
        args = ["test"] + (["--select", select] if select else [])
        result = self.invoke(args, quiet=quiet)
        passed, failed = self._parse_run_results()
        result.passed, result.failed = passed, failed
        # trust the parsed results when we have them; the exit code otherwise
        if passed or failed:
            result.ok = not failed
        return result

    # ------------------------------------------------------------------ #
    def _parse_run_results(self) -> tuple[list[str], list[str]]:
        path = self.dbt_dir / "target" / "run_results.json"
        if not path.exists():
            return [], []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return [], []

        passed: list[str] = []
        failed: list[str] = []
        for r in data.get("results", []):
            name = _readable(r.get("unique_id", ""))
            if str(r.get("status", "")).lower() in _PASS_STATUSES:
                passed.append(name)
            else:
                failed.append(name)
        return passed, failed


def _readable(unique_id: str) -> str:
    """Turn a dbt node id into the assertion name a human would recognise.

    dbt ids look like `test.<project>.<test_name>` for singular tests and
    `test.<project>.<test_name>.<hash>` for generated ones, e.g.
        test.fraud_pipeline.assert_avg_txn_amount_plausible
        test.fraud_pipeline.accepted_values_stg_transactions_is_fraud__0__1.f6d9ff0fc6
    The trailing hash is a uniqueness suffix and means nothing to a reader, so
    it is dropped — but only when it really is a hash, never when it is part of
    the name.
    """
    parts = [p for p in unique_id.split(".") if p]
    if not parts:
        return unique_id
    if _is_hash(parts[-1]) and len(parts) > 1:
        parts = parts[:-1]
    # test.<project>.<name> -> <name>
    return parts[2] if len(parts) >= 3 and parts[0] == "test" else parts[-1]


def _is_hash(segment: str) -> bool:
    return (len(segment) >= 8
            and all(c in "0123456789abcdef" for c in segment.lower()))
