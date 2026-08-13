"""Portable ingestion runner — no absolute paths.

Computes the repo root from this file's location, exports it (and the mlruns
file:// URI) so the YAML recipes resolve on any machine, runs both ingestions,
then wires ML lineage and applies governance.
"""
from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPES_DIR = Path(__file__).resolve().parent / "recipes"
MLRUNS_DIR = REPO_ROOT / "mlruns"

logger = logging.getLogger("sentinel.ingestion")


#: Liveness paths, in order. GMS serves /health; /healthcheck is a 404 on
#: current builds, and probing only that made this gate answer False against a
#: perfectly healthy server — which silently skipped the emit the detectors
#: depend on, so drills injected fine and then found nothing.
_HEALTH_PATHS = ("/health", "/config", "/healthcheck")


def is_gms_online(base_url: str = "http://localhost:8080", timeout: float = 5.0) -> bool:
    """Check if DataHub GMS REST server is running and responsive.

    Tries each known liveness path and accepts the first that answers, so a
    path being renamed between DataHub versions degrades to a slower check
    rather than a false negative.
    """
    root = base_url.rstrip("/")
    # Tolerate callers that already appended a health path.
    for path in _HEALTH_PATHS:
        if root.endswith(path):
            root = root[: -len(path)]
            break

    for path in _HEALTH_PATHS:
        try:
            req = urllib.request.Request(f"{root}{path}", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status in (200, 204, 301, 302, 401):
                    return True
        except Exception:
            continue
    return False


class IngestionRunner:
    """Runs the dbt + MLflow ingestion recipes, then lineage + governance."""

    def __init__(self, gms_url: str | None = None) -> None:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        os.environ.setdefault("DATAHUB_TELEMETRY_ENABLED", "false")
        # recipes reference these
        os.environ["DATAHUB_ROOT"] = REPO_ROOT.as_posix()
        os.environ["DATAHUB_MLRUNS_URI"] = MLRUNS_DIR.as_uri()
        # The recipes already resolve ${DATAHUB_GMS_URL}; the liveness probe and
        # the lineage/governance clients have to agree with them, or a remote
        # deployment probes localhost, declares GMS offline, and silently skips
        # the emit that the detectors depend on.
        self.gms_url = gms_url or os.environ.get(
            "DATAHUB_GMS_URL", "http://localhost:8080")

        self.recipes = [
            RECIPES_DIR / "dbt_recipe.yml",
            RECIPES_DIR / "mlflow_recipe.yml",
        ]

    def _run_recipe(self, path: Path) -> None:
        from datahub.configuration.config_loader import load_config_file
        from datahub.ingestion.run.pipeline import Pipeline

        print(f"\n=== ingesting: {path.name} ===")
        config = load_config_file(str(path), resolve_env_vars=True)
        pipeline = Pipeline.create(config)
        pipeline.run()
        pipeline.raise_from_status()
        print(f"--- {path.name}: {pipeline.source.get_report().events_produced} events ---")

    def run(self) -> None:
        if not is_gms_online(self.gms_url, timeout=5.0):
            print(f"\n[IngestionRunner] DataHub GMS ({self.gms_url}) is offline or unreachable.")
            print("[IngestionRunner] Skipping live GMS emit (Sentinel AST lineage engine remains active).\n")
            return

        for recipe in self.recipes:
            if not recipe.exists():
                raise FileNotFoundError(f"Recipe not found: {recipe}")
            try:
                self._run_recipe(recipe)
            except Exception as e:
                print(f"[IngestionRunner] Failed recipe {recipe.name}: {e}")

        try:
            from ingestion.lineage import LineageWirer
            from governance.policy import GovernanceApplier

            print("\n=== wiring ML lineage edges ===")
            LineageWirer(gms_server=self.gms_url).wire()

            print("\n=== applying governance (tags + owners) ===")
            GovernanceApplier(gms_server=self.gms_url).apply()

            print("\nAll ingestion complete.")
        except Exception as e:
            print(f"[IngestionRunner] Lineage wiring / governance failed: {e}")


if __name__ == "__main__":
    IngestionRunner().run()
