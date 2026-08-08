"""Load PagerDuty config from config/pagerduty.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_CONFIG_PATH = Path("config/pagerduty.yaml")


@dataclass
class PagerDutyConfig:
    enabled: bool = False
    routing_key: str = ""
    page_on_tiers: list[str] = field(default_factory=lambda: ["HUMAN_ONLY"])
    severity_map: dict[str, str] = field(default_factory=lambda: {
        "low": "critical",
        "medium": "error",
        "high": "warning",
    })

    @classmethod
    def load(cls) -> PagerDutyConfig:
        routing_key = os.environ.get("PAGERDUTY_ROUTING_KEY", "")

        if not _CONFIG_PATH.exists():
            return cls(routing_key=routing_key)

        try:
            raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            return cls(routing_key=routing_key)

        severity = raw.get("severity", {})
        if not isinstance(severity, dict):
            severity = {}

        return cls(
            enabled=raw.get("enabled", False),
            routing_key=routing_key,
            page_on_tiers=raw.get("page_on_tiers", ["HUMAN_ONLY"]),
            severity_map={
                "low": severity.get("low", "critical"),
                "medium": severity.get("medium", "error"),
                "high": severity.get("high", "warning"),
            },
        )
