"""Importing this package registers all probes (decorators run on import).

A probe turns a signal into grounded facts. Several run per incident and their
evidence is pooled, because the RCA is only as good as the numbers underneath it
— the LLM narrates what the probes found, it does not decide what happened.

Probes reporting on an anomalous column also report how far upstream it sits, so
the deepest finding wins: a symptom seen in a mart and its cause in the source
table look identical until you know which is which.
"""
from agent.tools.probes import (  # noqa: F401
    column_lineage_probe,
    data_profile_probe,
    dependency_impact_probe,
    duplicate_probe,
    freshness_probe,
    leakage_probe,
    model_eval_probe,
    prediction_drift_probe,
    skew_probe,
    volume_probe,
)
