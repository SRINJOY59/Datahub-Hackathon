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
