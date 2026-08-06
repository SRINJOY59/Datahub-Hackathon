"""Portable ingestion runner — no absolute paths.

Computes the repo root from this file's location, exports it (and the mlruns
file:// URI) so the YAML recipes resolve on any machine, runs both ingestions,
then wires ML lineage and applies governance.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPES_DIR = Path(__file__).resolve().parent / "recipes"
MLRUNS_DIR = REPO_ROOT / "mlruns"


class IngestionRunner:
    """Runs the dbt + MLflow ingestion recipes, then lineage + governance."""

    def __init__(self) -> None:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        os.environ.setdefault("DATAHUB_TELEMETRY_ENABLED", "false")
        # recipes reference these
        os.environ["DATAHUB_ROOT"] = REPO_ROOT.as_posix()
        os.environ["DATAHUB_MLRUNS_URI"] = MLRUNS_DIR.as_uri()

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
        for recipe in self.recipes:
            if not recipe.exists():
                raise FileNotFoundError(f"Recipe not found: {recipe}")
            self._run_recipe(recipe)

        from ingestion.lineage import LineageWirer
        from governance.policy import GovernanceApplier

        print("\n=== wiring ML lineage edges ===")
        LineageWirer().wire()

        print("\n=== applying governance (tags + owners) ===")
        GovernanceApplier().apply()

        print("\nAll ingestion complete.")


if __name__ == "__main__":
    IngestionRunner().run()
