"""SlackNotifier — the single entry point the orchestrator calls.

Each incident lifecycle event becomes one or more Slack messages, routed to the
right audience channel. Thread management keeps every update about one incident
in one thread per channel.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from agent.contracts import (
    ActionRecord,
    AutonomyTier,
    ContextBundle,
    CostEstimate,
    Incident,
    IncidentOutcome,
    RootCauseAnalysis,
)
from agent.integrations.slack import formatter
from agent.integrations.slack.approvals import ApprovalDecision, ApprovalHandler
from agent.integrations.slack.client import SlackClient
from agent.integrations.slack.config import SlackConfig

_THREADS_PATH = Path(".sentinel/slack_threads.json")


class SlackNotifier:
    def __init__(self, client: SlackClient, config: SlackConfig,
                 approval_handler: Optional[ApprovalHandler] = None) -> None:
        self.client = client
        self.config = config
        self.approvals = approval_handler or ApprovalHandler()
        self._threads: dict[str, dict[str, str]] = self._load_threads()

    # --- Lifecycle hooks (called by the orchestrator) --------------------- #

    def on_detect(
        self,
        incident: Incident,
        context: ContextBundle,
        rca: RootCauseAnalysis,
        cost: CostEstimate,
    ) -> None:
        """Announce an incident to all three channels."""
        eng_blocks, eng_text = formatter.detect_engineer(incident, context, rca, cost)
        ana_blocks, ana_text = formatter.detect_analyst(context, rca)
        exe_blocks, exe_text = formatter.detect_executive(context, rca, cost)

        self._post_and_track(incident.id, "engineer", eng_blocks, eng_text)
        self._post_and_track(incident.id, "analyst", ana_blocks, ana_text)
        self._post_and_track(incident.id, "executive", exe_blocks, exe_text)

        print(f"  [slack    ] announced {incident.id} to 3 channels")

    def on_resolve(
        self,
        incident: Incident,
        context: ContextBundle,
        rca: RootCauseAnalysis,
        cost: CostEstimate,
        outcome: IncidentOutcome,
    ) -> None:
        """Thread reply: resolved."""
        eng_blocks, eng_text = formatter.status_update(outcome)
        self._reply(incident.id, "engineer", eng_blocks, eng_text)
        self._react(incident.id, "engineer", "white_check_mark")

        ana_blocks, ana_text = formatter.resolve_analyst(context, resolved=True)
        self._reply(incident.id, "analyst", ana_blocks, ana_text)

        exe_blocks, exe_text = formatter.resolve_executive(context, cost, resolved=True)
        self._reply(incident.id, "executive", exe_blocks, exe_text)

        print(f"  [slack    ] updated {incident.id}: resolved")

    def on_contain(
        self,
        incident: Incident,
        context: ContextBundle,
        rca: RootCauseAnalysis,
        cost: CostEstimate,
        outcome: IncidentOutcome,
        failures: list[str],
    ) -> None:
        """Thread reply: contained, needs human."""
        extra = f"Still failing: {', '.join(failures)}" if failures else ""
        eng_blocks, eng_text = formatter.status_update(outcome, extra=extra)
        self._reply(incident.id, "engineer", eng_blocks, eng_text)
        self._react(incident.id, "engineer", "warning")

        ana_blocks, ana_text = formatter.resolve_analyst(context, resolved=False)
        self._reply(incident.id, "analyst", ana_blocks, ana_text)

        exe_blocks, exe_text = formatter.resolve_executive(context, cost, resolved=False)
        self._reply(incident.id, "executive", exe_blocks, exe_text)

        print(f"  [slack    ] updated {incident.id}: contained")

    def on_rollback(
        self,
        incident: Incident,
        context: ContextBundle,
        rca: RootCauseAnalysis,
        outcome: IncidentOutcome,
        failures: list[str],
    ) -> None:
        """Thread reply: rolled back, escalating."""
        extra = f"Validation still failing: {', '.join(failures)}" if failures else ""
        eng_blocks, eng_text = formatter.status_update(outcome, extra=extra)
        self._reply(incident.id, "engineer", eng_blocks, eng_text)
        self._react(incident.id, "engineer", "rewind")

        print(f"  [slack    ] updated {incident.id}: rolled back")

    def on_escalate(
        self,
        incident: Incident,
        context: ContextBundle,
        rca: RootCauseAnalysis,
        tier: AutonomyTier,
        reason: str,
    ) -> None:
        """Post escalation in the engineer thread."""
        text = f":rotating_light: *Escalating* — {reason}"
        if context.owners:
            mentions = " ".join(context.owners)
            text += f"\nOwners: {mentions}"
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
        self._reply(incident.id, "engineer", blocks, text)
        print(f"  [slack    ] escalated {incident.id}: {reason}")

    def request_approval(
        self,
        incident: Incident,
        actions: list[ActionRecord],
        context: ContextBundle,
        rca: RootCauseAnalysis,
    ) -> ApprovalDecision:
        """Post approve/deny buttons and block until a human responds.

        Returns the decision. If Socket Mode is not configured or the timeout
        expires, returns based on the fallback policy in config/slack.yaml.
        """
        blocks, text = formatter.approval_request(incident, actions, context, rca)
        self._reply(incident.id, "engineer", blocks, text)

        if not self.approvals.available:
            print(f"  [slack    ] approval posted for {incident.id} (no Socket Mode "
                  f"— applying fallback: {self.config.approval.fallback})")
            approved = self.config.approval.fallback != "deny"
            return ApprovalDecision(
                approved=approved, decided_by="fallback",
                timed_out=False,
            )

        timeout = self.config.approval.timeout_minutes * 60
        print(f"  [slack    ] waiting for approval on {incident.id} "
              f"(timeout: {self.config.approval.timeout_minutes}m)...")

        decision = self.approvals.wait_for_decision(incident.id, timeout)

        if decision.timed_out:
            print(f"  [slack    ] approval timed out for {incident.id} "
                  f"— applying fallback: {self.config.approval.fallback}")
            decision.approved = self.config.approval.fallback != "deny"
        else:
            verb = "approved" if decision.approved else "denied"
            print(f"  [slack    ] {incident.id} {verb} by {decision.decided_by}")

        return decision

    # --- Announce mode (used by `python -m agent notify`) ----------------- #

    def announce(
        self,
        incident: Incident,
        context: ContextBundle,
        rca: RootCauseAnalysis,
        cost: CostEstimate,
    ) -> None:
        """Same as on_detect but explicitly for the notify command."""
        self.on_detect(incident, context, rca, cost)

    # --- Thread management ------------------------------------------------ #

    def _post_and_track(
        self, incident_id: str, audience: str,
        blocks: list[dict], text: str,
    ) -> Optional[str]:
        channel = self.config.channels.get(audience, "")
        if not channel:
            return None
        ts = self.client.post_message(channel, blocks, text)
        if ts:
            self._threads.setdefault(incident_id, {})[audience] = ts
            self._save_threads()
        return ts

    def _reply(
        self, incident_id: str, audience: str,
        blocks: list[dict], text: str,
    ) -> Optional[str]:
        channel = self.config.channels.get(audience, "")
        thread_ts = self._threads.get(incident_id, {}).get(audience)
        if not channel:
            return None
        if thread_ts and self.config.one_thread_per_incident:
            return self.client.reply(channel, thread_ts, blocks, text)
        return self.client.post_message(channel, blocks, text)

    def _react(self, incident_id: str, audience: str, emoji: str) -> None:
        channel = self.config.channels.get(audience, "")
        thread_ts = self._threads.get(incident_id, {}).get(audience)
        if channel and thread_ts:
            self.client.add_reaction(channel, thread_ts, emoji)

    def _load_threads(self) -> dict[str, dict[str, str]]:
        if _THREADS_PATH.exists():
            try:
                return json.loads(_THREADS_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_threads(self) -> None:
        _THREADS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _THREADS_PATH.write_text(
            json.dumps(self._threads, indent=2),
            encoding="utf-8",
        )
