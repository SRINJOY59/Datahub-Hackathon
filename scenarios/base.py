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


def _ensure_dbt_catalog() -> None:
    """Make sure target/catalog.json exists, without losing the test results.

    `dbt docs generate` is the only command that writes the catalog, but it
    also overwrites run_results.json with its own all-success results — which
    would erase the very assertion failures the detectors key on and emit a
    green graph for a broken pipeline. So: only generate when the catalog is
    actually missing, and put run_results.json back afterwards.
    """
    target = DBT_DIR / "target"
    catalog = target / "catalog.json"
    if catalog.exists():
        return

    print("[reingest] no dbt catalog in this container, generating one...")
    run_results = target / "run_results.json"
    saved = run_results.read_bytes() if run_results.exists() else None
    try:
        run_dbt(["docs", "generate"])
    except Exception as exc:
        msg = str(exc).encode("ascii", "replace").decode("ascii")
        print(f"[reingest] dbt docs generate failed: {msg}")
    finally:
        if saved is not None:
            run_results.write_bytes(saved)  # restore the real test outcomes


def reingest() -> None:
    """Refresh DataHub so assertion results (and the incident) are visible.

    The dbt recipe reads target/catalog.json, which only `dbt docs generate`
    writes -- `run` and `test` do not. target/ is gitignored, so a fresh
    container has no catalog and the recipe dies on FileNotFoundError, taking
    the assertion results with it. That failure is invisible locally, where a
    catalog is always lying around from earlier runs.
    """
    sys.path.insert(0, str(REPO_ROOT))
    _ensure_dbt_catalog()

    try:
        from ingestion.runner import IngestionRunner
        IngestionRunner().run()
    except Exception as exc:
        msg = str(exc).encode("ascii", "replace").decode("ascii")
        print(f"[reingest] DataHub refresh skipped (GMS offline): {msg}")


def rescore(update_baseline: bool = False) -> str:
    """Run the scoring job against the rebuilt tables.

    Some breakages only become visible once the model has actually scored the new
    data. `update_baseline` decides which question the scenario is asking: left
    alone, the new snapshot is compared against the old baseline and *prediction
    drift* shows up; updated, the baseline moves with the data and only the gap
    against the model's **training** distribution remains — which is
    training/serving skew, a different problem with a different fix.
    """
    from ml.score import BASELINE_PATH, SNAPSHOT_PATH, score

    snap = score()
    SNAPSHOT_PATH.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    if update_baseline:
        BASELINE_PATH.write_text(json.dumps(snap, indent=2), encoding="utf-8")

    return (f"scored {snap['n_scored']} rows: positive rate "
            f"{(snap.get('positive_pred_rate') or 0.0):.4f}"
            + ("; scoring baseline moved with it" if update_baseline else ""))


def retrain() -> str:
    """Retrain and re-register the champion on whatever the tables now hold."""
    from ml.train import main as train_main

    train_main()
    return "retrained the champion on the current data"


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
        row = con.execute(
            "select quantile_cont(epoch(txn_timestamp), ?) from raw_transactions",
            [1 - self.recent_fraction],
        ).fetchone()
        cutoff = row[0] if row and row[0] is not None else 0
        return f"epoch(txn_timestamp) >= {cutoff}"

    @abstractmethod
    def inject(self, con: duckdb.DuckDBPyConnection) -> str:
        """Corrupt raw_transactions in place. Return a human description."""

    def post_build(self) -> str:
        """Anything that must happen after the models rebuild.

        Some breakages only become visible once the ML side has run on the new
        data — a drift signal needs a fresh scoring snapshot, a leaked label
        needs a retrained model. Those steps read the rebuilt tables, so they
        cannot run before dbt does. Returns a description, or '' when there is
        nothing to do (which is the case for every purely-data scenario).
        """
        return ""

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

        follow_up = self.post_build()
        if follow_up:
            print(f"\n[{self.name}] {follow_up}")

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
        if reingest_after:
            print(f"\n[{self.name}] refreshing DataHub...")
            reingest()
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

    "Last known good" has to mean every reference the agent compares against —
    the table snapshots, the volume and freshness baseline, the champion alias,
    and the scoring baseline. Leaving any one of them behind lets a scenario's
    deliberate perturbation outlive the reset and quietly change what the next
    run detects.
    """

    def run(self, reingest_after: bool = True) -> bool:
        self._cleanup_scenarios()
        self._clear_agent_state()

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
    def _clear_agent_state() -> None:
        """Release anything the agent left holding the pipeline open, and discard
        per-incident restore points. A breaker that outlives its incident would
        silently keep the scoring job down; stale `pre_*` snapshots would pile up
        one per action forever."""
        try:
            from agent.tools.actuators.pause_job import clear_all
            from agent.tools.warehouse.snapshots import SnapshotStore
        except ImportError:
            return

        n = clear_all()
        if n:
            print(f"[reset] closed {n} open circuit breaker(s)")

        dropped = SnapshotStore().drop_incident_snapshots()
        if dropped:
            print(f"[reset] discarded {dropped} per-incident restore point(s)")

        cleared = _clear_degraded_tags()
        if cleared:
            print(f"[reset] removed Sentinel-Degraded from {cleared} asset(s)")

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

        # The scoring baseline is part of "last known good" too, and it is the
        # one piece a scenario can move permanently: training_serving_skew
        # deliberately advances it, which is how it isolates skew from drift.
        # Without re-anchoring here that shifted baseline outlives the reset and
        # silently blinds the drift detector for every later run — a 1.4x shift
        # measured against an already-1.6x reference reads as no drift at all.
        try:
            print(f"[reset] {rescore(update_baseline=True)}")
        except Exception as e:
            print(f"[reset] could not re-anchor the scoring baseline "
                  f"({type(e).__name__}) — drift comparisons may be stale")


def _clear_degraded_tags() -> int:
    """Take the agent's warning tags back off the graph.

    A contained incident deliberately leaves `Sentinel-Degraded` in place, which
    is right while the incident is open — but a reset declares the world healthy
    again. Without this the warnings outlive the problems and every asset in the
    catalog eventually looks permanently suspect, which is the fastest way to
    make people stop reading them.
    """
    try:
        import datahub.emitter.mce_builder as builder
        from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
        from datahub.metadata.schema_classes import GlobalTagsClass
        from datahub.emitter.mcp import MetadataChangeProposalWrapper

        from agent.tools.actuators.tag_asset import DEGRADED_TAG
    except ImportError:
        return 0

    try:
        gms = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
        graph = DataHubGraph(DataHubGraphConfig(server=gms))
        tag_urn = builder.make_tag_urn(DEGRADED_TAG)
        urns = graph.get_urns_by_filter(entity_types=["dataset"], platform="dbt")
    except Exception:
        return 0

    cleared = 0
    for urn in list(urns):
        try:
            tags = graph.get_aspect(urn, GlobalTagsClass)
            if not tags:
                continue
            remaining = [t for t in tags.tags if t.tag != tag_urn]
            if len(remaining) == len(tags.tags):
                continue
            graph.emit_mcp(MetadataChangeProposalWrapper(
                entityUrn=urn, aspect=GlobalTagsClass(tags=remaining)))
            cleared += 1
        except Exception:
            continue
    return cleared


def capture_last_good(reingest_after: bool = False) -> None:
    """Manual entry point: `python -m scenarios snapshot`."""
    PipelineReset._capture_last_good()
