"""Load Slack settings from config/slack.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "slack.yaml"


@dataclass
class ApprovalConfig:
    timeout_minutes: int = 30
    fallback: str = "protective_only"


@dataclass
class SlackConfig:
    enabled: bool = False
    channels: dict[str, str] = field(default_factory=lambda: {
        "engineer": "#sentinel-oncall",
        "analyst": "#data-quality",
        "executive": "#sentinel-exec",
    })
    approval: ApprovalConfig = field(default_factory=ApprovalConfig)
    one_thread_per_incident: bool = True

    @classmethod
    def load(cls) -> SlackConfig:
        if not _CONFIG_PATH.exists():
            return cls()

        with open(_CONFIG_PATH, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        if not raw.get("enabled", False):
            return cls(enabled=False)

        bot_token = os.getenv("SLACK_BOT_TOKEN", "")
        if not bot_token:
            return cls(enabled=False)

        channels = raw.get("channels", {})
        approval_raw = raw.get("approval", {})
        threading = raw.get("threading", {})

        return cls(
            enabled=True,
            channels={
                "engineer": channels.get("engineer", "#sentinel-oncall"),
                "analyst": channels.get("analyst", "#data-quality"),
                "executive": channels.get("executive", "#sentinel-exec"),
            },
            approval=ApprovalConfig(
                timeout_minutes=approval_raw.get("timeout_minutes", 30),
                fallback=approval_raw.get("fallback", "protective_only"),
            ),
            one_thread_per_incident=threading.get("one_thread_per_incident", True),
        )
