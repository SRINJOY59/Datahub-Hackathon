"""Pydantic schemas for LLM structured outputs.

Using a schema (instead of parsing free text) makes the agent robust to chatty /
reasoning models: we get validated fields or a clean fallback, never a half-
parsed sentence.

`change_type` references the ChangeType enum directly rather than restating its
members as a Literal. An earlier hand-written Literal listed only some of them,
which under strict json_schema forced the model to pick a wrong value for the
incident classes it omitted. Pointing at the enum makes that drift impossible.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent.contracts import ChangeType


class RCAResult(BaseModel):
    """The LLM's synthesis over grounded evidence."""

    root_cause: str = Field(
        description="One sentence naming the upstream asset/column and the change, citing evidence."
    )
    change_type: ChangeType = Field(description="The classified anomaly type.")
    confidence: Literal["low", "medium", "high"]
    recommended_mitigation: str = Field(
        description="The single reversible action to take first."
    )


class Runbook(BaseModel):
    """A procedure distilled from incidents that were actually resolved."""

    title: str = Field(description="Short imperative title, e.g. 'Handle a null spike in an upstream feed'.")
    summary: str = Field(description="One sentence: what this class of incident is and why it matters.")
    symptoms: list[str] = Field(description="How this shows up — what breaks, what stays green.")
    diagnosis_steps: list[str] = Field(description="Ordered checks that confirm the diagnosis.")
    mitigation_steps: list[str] = Field(description="Ordered actions that have actually resolved this here.")
    verification_steps: list[str] = Field(description="How to confirm the pipeline is healthy again.")
    required_tools: list[str] = Field(default_factory=list,
                                      description="Tools or commands the steps depend on.")

    def as_instructions(self) -> str:
        """Flatten to the single instructions block DataHub's AgentSkill holds.

        The tool list is folded in here rather than sent to the aspect's
        `requiredTools` field: despite the name, that field holds DataHub *urns*
        and rejects prose, and what the model produces is a description of what
        you need rather than a pointer to a catalogued tool.
        """
        def section(heading: str, items: list[str]) -> str:
            if not items:
                return ""
            body = "\n".join(f"{i}. {step}" for i, step in enumerate(items, 1))
            return f"\n## {heading}\n{body}\n"

        return (f"# {self.title}\n\n{self.summary}\n"
                + section("Symptoms", self.symptoms)
                + section("Diagnosis", self.diagnosis_steps)
                + section("Mitigation", self.mitigation_steps)
                + section("Verification", self.verification_steps)
                + section("Requires", self.required_tools)).strip()
