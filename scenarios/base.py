"""Base class + shared machinery for incident scenarios.

A Scenario injects a specific upstream failure into the fraud pipeline, rebuilds
downstream models, runs the assertions (which should now fail), and refreshes
DataHub so the incident is visible to the agent. `Scenario.reset()` restores a
clean, healthy state between demo takes.
"""
from __future__ import annotations

import os
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = REPO_ROOT / "pipeline" / "dbt"
DUCKDB_PATH = DBT_DIR / "fraud.duckdb"

_DBT_EXE = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")


def run_dbt(args: list[str]) -> bool:
    """Run dbt in a subprocess (avoids DuckDB single-writer lock contention with
    an in-process connection). Returns True on success."""
    cmd = [str(_DBT_EXE), *args, "--profiles-dir", str(DBT_DIR),
           "--project-dir", str(DBT_DIR)]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(cmd, cwd=str(DBT_DIR), env=env).returncode == 0


def reingest() -> None:
    """Refresh DataHub so assertion results (and the incident) are visible."""
    sys.path.insert(0, str(REPO_ROOT))
    from ingestion.runner import IngestionRunner

    IngestionRunner().run()


class Scenario(ABC):
    """One named incident scenario."""

    name: str = ""
    description: str = ""
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

        print(f"\n[{self.name}] running assertions (expect FAILURES — the trigger)...")
        ok = run_dbt(["test"])
        print(f"\n[{self.name}] assertions passed: {ok}  "
              + ("(unexpected)" if ok else "<-- incident detected by dbt assertions"))

        if reingest_after:
            print(f"\n[{self.name}] refreshing DataHub...")
            reingest()
        print(f"\n[{self.name}] done. Incident is live in DataHub.")

    @staticmethod
    def reset(reingest_after: bool = True) -> None:
        print("[reset] re-seeding clean raw data...")
        run_dbt(["seed", "--full-refresh"])
        print("\n[reset] rebuilding models...")
        run_dbt(["run"])
        print("\n[reset] verifying assertions...")
        ok = run_dbt(["test"])
        print(f"\n[reset] assertions passed: {ok}")
        if reingest_after:
            print("\n[reset] refreshing DataHub...")
            reingest()
        print("\n[reset] pipeline restored to healthy state.")
