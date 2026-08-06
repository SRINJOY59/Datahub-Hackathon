"""Composite Mechanisms wiring real tools where they exist and falling back to
fakes for the rest — so the agent runs end-to-end while tools are built one at a
time.

Currently real:  detect_incidents, read_context  (DataHubContextTool)
Still faked:      run_checks, act, undo, propose_fix, write_back
"""
from __future__ import annotations

from agent.contracts import (
    ActionRecord,
    ContextBundle,
    Incident,
    Mechanisms,
    PostMortem,
    ValidationResult,
)
from agent.tools.datahub_context import DataHubContextTool
from agent.tools.fakes import FakeMechanisms


class RealMechanisms(Mechanisms):
    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.context = DataHubContextTool(gms_server)
        self._fake = FakeMechanisms()  # placeholder for not-yet-built tools

    # --- real ---
    def detect_incidents(self) -> list[Incident]:
        return self.context.detect_incidents()

    def read_context(self, asset_urn: str) -> ContextBundle:
        return self.context.read_context(asset_urn)

    # --- still faked (Phase 3 continues) ---
    def run_checks(self, asset_urn: str) -> ValidationResult:
        return self._fake.run_checks(asset_urn)

    def act(self, action: ActionRecord) -> ActionRecord:
        return self._fake.act(action)

    def undo(self, action: ActionRecord) -> bool:
        return self._fake.undo(action)

    def propose_fix(self, context: ContextBundle, root_cause: str) -> str:
        return self._fake.propose_fix(context, root_cause)

    def write_back(self, post_mortem: PostMortem) -> None:
        return self._fake.write_back(post_mortem)
