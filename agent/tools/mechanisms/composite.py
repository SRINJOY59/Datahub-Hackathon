"""Composite Mechanisms wiring real tools where they exist and falling back to
fakes for the rest — so the agent runs end-to-end while tools are built one at a
time.

Currently real:  detect_incidents (all registered detectors), read_context,
                 propose_fix (CodeFixTool).
Still faked:      run_checks, act, undo, write_back.
"""
from __future__ import annotations

from typing import Optional

from agent.contracts import (
    ActionRecord,
    ContextBundle,
    Incident,
    Mechanisms,
    PostMortem,
    ValidationResult,
)
from agent.llm import LLMClient
from agent.registry import build_detectors
from agent.tools.codefix.generator import CodeFixTool
from agent.tools.graph.context import DataHubContextTool
from agent.tools.mechanisms.fakes import FakeMechanisms

# import plugin packages so detectors/probes register
import agent.tools.detectors  # noqa: F401
import agent.tools.probes  # noqa: F401


class RealMechanisms(Mechanisms):
    def __init__(self, gms_server: str = "http://localhost:8080",
                 llm: Optional[LLMClient] = None) -> None:
        self.context = DataHubContextTool(gms_server)
        self.detectors = build_detectors(gms_server)
        self.codefix = CodeFixTool(llm=llm)
        self._fake = FakeMechanisms()  # placeholder for not-yet-built tools

    # --- real ---
    def detect_incidents(self) -> list[Incident]:
        incidents: list[Incident] = []
        for d in self.detectors:
            try:
                incidents.extend(d.detect())
            except Exception:  # a flaky detector must not sink the run
                pass
        return incidents

    def read_context(self, asset_urn: str) -> ContextBundle:
        return self.context.read_context(asset_urn)

    def propose_fix(self, incident: Incident, context: ContextBundle,
                    root_cause: str) -> str:
        return self.codefix.propose_fix(incident, context, root_cause)

    # --- still faked ---
    def run_checks(self, asset_urn: str) -> ValidationResult:
        return self._fake.run_checks(asset_urn)

    def act(self, action: ActionRecord) -> ActionRecord:
        return self._fake.act(action)

    def undo(self, action: ActionRecord) -> bool:
        return self._fake.undo(action)

    def write_back(self, post_mortem: PostMortem) -> None:
        return self._fake.write_back(post_mortem)
