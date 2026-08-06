"""Pydantic schemas for LLM structured outputs.

Using a schema (instead of parsing free text) makes the agent robust to chatty /
reasoning models: we get validated fields or a clean fallback, never a half-
parsed sentence.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RCAResult(BaseModel):
    """The LLM's synthesis over grounded evidence."""

    root_cause: str = Field(
        description="One sentence naming the upstream asset/column and the change, citing evidence."
    )
    change_type: Literal[
        "null_spike", "scale_shift", "range_violation",
        "schema_change", "distribution_drift", "unknown",
    ] = Field(description="The classified anomaly type.")
    confidence: Literal["low", "medium", "high"]
    recommended_mitigation: str = Field(
        description="The single reversible action to take first."
    )
