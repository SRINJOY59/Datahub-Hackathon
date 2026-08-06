"""Importing this package registers all probes (decorators run on import)."""
from agent.tools.probes import (  # noqa: F401
    column_lineage_probe,
    data_profile_probe,
    dependency_impact_probe,
    model_eval_probe,
)
