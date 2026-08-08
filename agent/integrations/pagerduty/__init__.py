"""PagerDuty integration — page humans for critical incidents."""
from __future__ import annotations

from typing import Optional

_instance: Optional["PagerDutyClient"] = None


def shared_pagerduty() -> Optional["PagerDutyClient"]:
    """Singleton — returns None when PagerDuty is not configured."""
    global _instance
    if _instance is not None:
        return _instance

    from agent.integrations.pagerduty.config import PagerDutyConfig
    from agent.integrations.pagerduty.client import PagerDutyClient

    cfg = PagerDutyConfig.load()
    if not cfg.enabled or not cfg.routing_key:
        return None

    _instance = PagerDutyClient(cfg)
    print("  [pagerduty] connected — will page on "
          f"{', '.join(cfg.page_on_tiers)} incidents")
    return _instance
