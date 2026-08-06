from __future__ import annotations

import os
import sys
from pathlib import Path

# Windows consoles default to cp1252; DataHub prints unicode. Force UTF-8.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("DATAHUB_TELEMETRY_ENABLED", "false")

REPO_ROOT = Path(__file__).resolve().parent
MLRUNS_DIR = REPO_ROOT / "mlruns"

# Recipes reference these; set them before loading any recipe.
os.environ["DATAHUB_ROOT"] = REPO_ROOT.as_posix()
os.environ["DATAHUB_MLRUNS_URI"] = MLRUNS_DIR.as_uri()

RECIPES = [
    REPO_ROOT / "config" / "dbt_recipe.yml",
    REPO_ROOT / "config" / "mlflow_recipe.yml",
]


def run_recipe(path: Path) -> None:
    from datahub.configuration.config_loader import load_config_file
    from datahub.ingestion.run.pipeline import Pipeline

    print(f"\n=== ingesting: {path.name} ===")
    config = load_config_file(str(path), resolve_env_vars=True)
    pipeline = Pipeline.create(config)
    pipeline.run()
    pipeline.raise_from_status()
    print(f"--- {path.name}: {pipeline.source.get_report().events_produced} events ---")


def main() -> None:
    for recipe in RECIPES:
        if not recipe.exists():
            sys.exit(f"Recipe not found: {recipe}")
        run_recipe(recipe)

    print("\n=== wiring ML lineage edges ===")
    sys.path.insert(0, str(REPO_ROOT / "ml"))
    import wire_lineage

    wire_lineage.main()
    print("\nAll ingestion complete.")


if __name__ == "__main__":
    main()
