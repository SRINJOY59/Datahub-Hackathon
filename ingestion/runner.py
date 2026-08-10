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


def is_gms_online(url: str = "http://localhost:8080/healthcheck", timeout: float = 3.0) -> bool:
    """Check if DataHub GMS REST server is running and responsive."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 204, 301, 302, 401)
    except Exception:
        return False


class IngestionRunner:
    """Runs the dbt + MLflow ingestion recipes, then lineage + governance."""

    def __init__(self, gms_url: str = "http://localhost:8080") -> None:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        os.environ.setdefault("DATAHUB_TELEMETRY_ENABLED", "false")
        # recipes reference these
        os.environ["DATAHUB_ROOT"] = REPO_ROOT.as_posix()
        os.environ["DATAHUB_MLRUNS_URI"] = MLRUNS_DIR.as_uri()
        self.gms_url = gms_url

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
        if not is_gms_online(f"{self.gms_url.rstrip('/')}/healthcheck", timeout=3.0):
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
