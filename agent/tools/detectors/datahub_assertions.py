"""Detector: surfaces incidents from failed DataHub assertions.

The first registered detector. Future detectors (model drift, dependency change,
git commit, freshness, training-metric regression) register the same way.
"""
from __future__ import annotations

from agent.contracts import Incident
from agent.registry import detector
from agent.tools.graph.context import DataHubContextTool


@detector
class DataHubAssertionDetector:
    name = "datahub_assertions"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.context = DataHubContextTool(gms_server)

    def detect(self) -> list[Incident]:
        return self.context.detect_incidents()
