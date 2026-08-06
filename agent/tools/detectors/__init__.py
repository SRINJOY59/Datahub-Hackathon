"""Importing this package registers all detectors (decorators run on import)."""
from agent.tools.detectors import (  # noqa: F401
    datahub_assertions,
    dependency,
    training_metrics,
)
