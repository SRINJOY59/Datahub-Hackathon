"""Slack integration for Sentinel incident notifications and approvals."""
from __future__ import annotations

from typing import Optional

_instance: Optional["SlackNotifier"] = None


def shared_slack() -> Optional["SlackNotifier"]:
    """Singleton — returns None when Slack is not configured."""
    global _instance
    if _instance is not None:
        return _instance

    from agent.integrations.slack.client import SlackClient
    from agent.integrations.slack.config import SlackConfig

    cfg = SlackConfig.load()
    if not cfg.enabled:
        return None

    client = SlackClient()
    if not client.available():
        return None

    from agent.integrations.slack.notifier import SlackNotifier

    _instance = SlackNotifier(client=client, config=cfg)
    return _instance
