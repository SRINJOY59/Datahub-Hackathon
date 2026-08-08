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

    from agent.integrations.slack.approvals import ApprovalHandler
    from agent.integrations.slack.notifier import SlackNotifier

    handler = ApprovalHandler()
    if handler.start_socket_mode():
        print("  [slack    ] Socket Mode connected — interactive approvals enabled")
    else:
        print("  [slack    ] Socket Mode not configured (set SLACK_APP_TOKEN for "
              "interactive approvals)")

    _instance = SlackNotifier(client=client, config=cfg, approval_handler=handler)
    return _instance
