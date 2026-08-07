"""Scenario framework — the incidents we deliberately cause, so we can prove the
agent handles them.

Three kinds of scenario share one root:

    BaseScenario (ABC)
      |- DataScenario      corrupts the warehouse, rebuilds dbt models, runs
      |                    assertions; the incident surfaces in DataHub
      |- AdvisoryScenario  publishes a vendor advisory; no dbt rebuild, the
      |                    dependency detector reads the file and scans the code
      `- ModelScenario     acts on the ML side (MLflow registry, scoring
                           snapshot); no warehouse corruption

Every scenario also declares an `Expectation`: what the agent is *supposed* to
conclude and do about it. That turns each scenario into an executable test case
(see scenarios/verify.py) instead of something a human has to eyeball.

`cleanup()` is the counterpart of `apply()`: PipelineReset calls it on every
scenario, so restoring a clean world doesn't depend on remembering which
scenario was run last.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = REPO_ROOT / "pipeline" / "dbt"
DUCKDB_PATH = DBT_DIR / "fraud.duckdb"
SENTINEL_DIR = REPO_ROOT / ".sentinel"
ADVISORIES_DIR = SENTINEL_DIR / "advisories"

_DBT_EXE = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")


# --------------------------------------------------------------------------- #
# Expectations — what "the agent got this right" means, per scenario
# --------------------------------------------------------------------------- #
@dataclass
class Expectation:
    """The verifiable contract of a scenario. Every field is optional so a
    scenario can assert only what it can honestly predict."""
    signal_type: Optional[str] = None        # SignalType value the detector should emit
    change_type: Optional[str] = None        # ChangeType value RCA should land on
    root_table: Optional[str] = None         # table RCA should blame
    root_column: Optional[str] = None        # column RCA should blame
    actions: list[str] = field(default_factory=list)   # ActionType values, in order
    checks_pass_after_act: bool = True       # does mitigation restore a green gate?
    trips_dbt_tests: bool = True             # False = silent failure, dbt stays green
    note: str = ""


# --------------------------------------------------------------------------- #
# Shared machinery
# --------------------------------------------------------------------------- #
def write_advisory(name: str, advisory: dict) -> Path:
    ADVISORIES_DIR.mkdir(parents=True, exist_ok=True)
    path = ADVISORIES_DIR / f"{name}.json"
    path.write_text(json.dumps(advisory, indent=2), encoding="utf-8")
    return path


def clear_advisories() -> int:
    if not ADVISORIES_DIR.exists():
        return 0
    files = list(ADVISORIES_DIR.glob("*.json"))
    for f in files:
        f.unlink()
    return len(files)


def run_dbt(args: list[str]) -> bool:
    """Run dbt in a subprocess. Delegates to the agent's DbtRunner so there is a
    single dbt invocation path in the repo; falls back to a direct subprocess if
    the agent package isn't importable (keeps scenarios standalone-runnable)."""
    try:
        from agent.tools.warehouse.dbt_runner import DbtRunner

        return DbtRunner().invoke(args).ok
    except ImportError:
        cmd = [str(_DBT_EXE), *args, "--profiles-dir", str(DBT_DIR),
               "--project-dir", str(DBT_DIR)]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        return subprocess.run(cmd, cwd=str(DBT_DIR), env=env).returncode == 0


def reingest() -> None:
    """Refresh DataHub so assertion results (and the incident) are visible."""
    sys.path.insert(0, str(REPO_ROOT))
    from ingestion.runner import IngestionRunner

    IngestionRunner().run()


# --------------------------------------------------------------------------- #
# The scenario hierarchy
# --------------------------------------------------------------------------- #
class BaseScenario(ABC):
    """One named way the world can break."""

    name: str = ""
    description: str = ""
    expectation: Expectation = Expectation()

    @abstractmethod
    def apply(self, reingest_after: bool = True) -> None:
        """Break something. Leaves the system in a state the agent should detect."""

    def cleanup(self) -> None:
        """Undo anything this scenario changed *outside* the warehouse seed data
        (advisories, MLflow aliases, breaker files). Warehouse state is restored
        wholesale by PipelineReset's re-seed, so most scenarios need nothing here.
        Must be safe to call when the scenario was never applied."""
        return None


class DataScenario(BaseScenario):
    """Corrupts raw_transactions, rebuilds the downstream dbt models, and runs the
    assertions — which is what makes the incident visible to DataHub."""

    recent_fraction: float = 0.20  # fraction of most-recent transactions to corrupt

    def recent_clause(self, con: duckdb.DuckDBPyConnection) -> str:
        """SQL predicate selecting the most-recent `recent_fraction` of rows."""
        cutoff = con.execute(
            "select quantile_cont(epoch(txn_timestamp), ?) from raw_transactions",
            [1 - self.recent_fraction],
        ).fetchone()[0]
        return f"epoch(txn_timestamp) >= {cutoff}"

    @abstractmethod
    def inject(self, con: duckdb.DuckDBPyConnection) -> str:
        """Corrupt raw_transactions in place. Return a human description."""

    def apply(self, reingest_after: bool = True) -> None:
        con = duckdb.connect(str(DUCKDB_PATH))
        try:
            desc = self.inject(con)
        finally:
            con.close()

        print(f"[{self.name}] {desc}")
        print(f"\n[{self.name}] rebuilding downstream models from poisoned raw...")
        run_dbt(["run"])

        expect_green = not self.expectation.trips_dbt_tests
        print(f"\n[{self.name}] running assertions "
              f"({'expect PASS — this failure is silent' if expect_green else 'expect FAILURES — the trigger'})...")
        ok = run_dbt(["test"])
        if expect_green:
            print(f"\n[{self.name}] assertions passed: {ok}  "
                  + ("<-- silent failure: dbt is happy, the pipeline is not"
                     if ok else "(unexpected — a test caught it)"))
        else:
            print(f"\n[{self.name}] assertions passed: {ok}  "
                  + ("(unexpected)" if ok else "<-- incident detected by dbt assertions"))

        if reingest_after:
            print(f"\n[{self.name}] refreshing DataHub...")
            reingest()
        print(f"\n[{self.name}] done. Incident is live in DataHub.")


class AdvisoryScenario(BaseScenario):
    """A non-data scenario: publishes a vendor advisory (an external API/package
    breaking change). No dbt rebuild — the dependency detector reads the advisory
    and scans the codebase."""

    advisory: dict = {}

    def apply(self, reingest_after: bool = True) -> None:  # arg kept for a uniform CLI
        path = write_advisory(self.name, self.advisory)
        pkg = self.advisory.get("package")
        print(f"[{self.name}] published advisory for {pkg}: "
              f"{self.advisory.get('from_version')} -> {self.advisory.get('to_version')}")
        print(f"[{self.name}] wrote {path.relative_to(REPO_ROOT).as_posix()}")
        print(f"\n[{self.name}] done. Run `python -m agent` to detect + auto-fix.")

    def cleanup(self) -> None:
        path = ADVISORIES_DIR / f"{self.name}.json"
        if path.exists():
            path.unlink()


class ModelScenario(BaseScenario):
    """Acts on the ML side — the MLflow registry or the scoring snapshot — rather
    than the warehouse. Restoring these is not covered by re-seeding dbt, so
    subclasses carry their own cleanup()."""

    @abstractmethod
    def perturb(self) -> str:
        """Degrade the ML side. Return a human description."""

    def apply(self, reingest_after: bool = True) -> None:
        desc = self.perturb()
        print(f"[{self.name}] {desc}")
        print(f"\n[{self.name}] done. Run `python -m agent` to detect.")


# --------------------------------------------------------------------------- #
# Restoring a clean world
# --------------------------------------------------------------------------- #
class PipelineReset:
    """Returns the whole system to a healthy baseline.

    Reset is a pipeline-wide operation, not something any one scenario owns: it
    asks every registered scenario to clean up after itself, then rebuilds the
    warehouse from seed and re-captures the 'last known good' state that the
    Time Machine rolls back to.
    """

    def run(self, reingest_after: bool = True) -> bool:
        self._cleanup_scenarios()

        n = clear_advisories()
        if n:
            print(f"[reset] cleared {n} advisory file(s)")

        print("[reset] re-seeding clean raw data...")
        run_dbt(["seed", "--full-refresh"])
        print("\n[reset] rebuilding models...")
        run_dbt(["run"])
        print("\n[reset] verifying assertions...")
        ok = run_dbt(["test"])
        print(f"\n[reset] assertions passed: {ok}")

        if ok:
            self._capture_last_good()
        else:
            print("[reset] assertions failed — NOT capturing a last-good snapshot "
                  "(we would be freezing a broken state)")

        if reingest_after:
            print("\n[reset] refreshing DataHub...")
            reingest()
        print("\n[reset] pipeline restored to healthy state.")
        return ok

    # ------------------------------------------------------------------ #
    @staticmethod
    def _cleanup_scenarios() -> None:
        from scenarios.registry import all_scenarios

        for cls in all_scenarios():
            try:
                cls().cleanup()
            except Exception as e:  # a scenario's cleanup must not block the reset
                print(f"[reset] cleanup for {cls.name} failed: {type(e).__name__}: {e}")

    @staticmethod
    def _capture_last_good() -> None:
        """Snapshot the healthy warehouse + record its shape. This is what
        PIN_FEATURE restores to and what the volume/freshness detectors compare
        against — without it the Time Machine has nowhere to roll back to."""
        try:
            from agent.tools.warehouse.baselines import BaselineStore
            from agent.tools.warehouse.snapshots import SnapshotStore
        except ImportError:
            return

        tables = SnapshotStore().capture_all(label="last_good")
        print(f"[reset] captured last-good snapshot of {len(tables)} table(s)")
        BaselineStore().capture()
        print("[reset] captured volume/freshness baseline")


def capture_last_good(reingest_after: bool = False) -> None:
    """Manual entry point: `python -m scenarios snapshot`."""
    PipelineReset._capture_last_good()
