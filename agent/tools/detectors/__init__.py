"""Importing this package registers all detectors (decorators run on import).

Detectors are the agent's senses, and they deliberately watch different things.
Three read a source of truth outside the warehouse — DataHub's assertion results,
vendor advisories, the MLflow registry. The rest exist because the most dangerous
failures are the ones every assertion passes through: a feed that stopped, a
batch that halved, features that drifted away from what the model learned, or a
model that got suspiciously good because the label leaked into it.
"""
from agent.tools.detectors import (  # noqa: F401
    datahub_assertions,
    dependency,
    freshness,
    leakage,
    model_drift,
    training_metrics,
    training_serving_skew,
    volume,
)
