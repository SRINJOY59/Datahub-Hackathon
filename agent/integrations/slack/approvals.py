"""Interactive approval handler — makes the approve/deny buttons work.

When the orchestrator needs human approval (PR_ONLY or HUMAN_ONLY tier), it
posts buttons to Slack and blocks until a human clicks one or the timeout
expires. This module bridges the gap: a Socket Mode listener runs on a
background thread and resolves pending approvals when a button click arrives.

Without SLACK_APP_TOKEN, approvals degrade to the configured fallback policy
(default: protective_only). The agent never hangs waiting for a token that
isn't configured.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ApprovalDecision:
    approved: bool
    decided_by: str = ""
    decided_at: Optional[datetime] = None
    timed_out: bool = False


@dataclass
class _PendingApproval:
    incident_id: str
    event: threading.Event = field(default_factory=threading.Event)
    decision: Optional[ApprovalDecision] = None


class ApprovalHandler:
    """Manages pending approvals and resolves them from Slack interactions."""

    def __init__(self) -> None:
        self._pending: dict[str, _PendingApproval] = {}
        self._socket_running = False

    def start_socket_mode(self) -> bool:
        """Start the Socket Mode listener on a background thread.

        Returns True if started, False if SLACK_APP_TOKEN is not set.
        """
        app_token = os.getenv("SLACK_APP_TOKEN", "")
        bot_token = os.getenv("SLACK_BOT_TOKEN", "")
        if not app_token or not bot_token:
            return False

        try:
            from slack_sdk.socket_mode import SocketModeClient
            from slack_sdk.socket_mode.request import SocketModeRequest
            from slack_sdk.socket_mode.response import SocketModeResponse
            from slack_sdk.web import WebClient
        except ImportError:
            return False

        web_client = WebClient(token=bot_token)
        socket_client = SocketModeClient(app_token=app_token, web_client=web_client)

        def _handle(client: SocketModeClient, req: SocketModeRequest) -> None:
            if req.type != "interactive":
                return
            client.send_socket_mode_response(
                SocketModeResponse(envelope_id=req.envelope_id),
            )
            payload = req.payload or {}
            actions = payload.get("actions", [])
            if not actions:
                return

            action = actions[0]
            action_id = action.get("action_id", "")
            incident_id = action.get("value", "")
            user = payload.get("user", {}).get("name", "unknown")

            if action_id == "sentinel_approve":
                self._resolve(incident_id, approved=True, user=user)
                self._update_message(web_client, payload, user, approved=True)
            elif action_id == "sentinel_deny":
                self._resolve(incident_id, approved=False, user=user)
                self._update_message(web_client, payload, user, approved=False)

        socket_client.socket_mode_request_listeners.append(_handle)

        thread = threading.Thread(target=socket_client.connect, daemon=True)
        thread.start()
        self._socket_running = True
        return True

    @property
    def available(self) -> bool:
        return self._socket_running

    def wait_for_decision(
        self,
        incident_id: str,
        timeout_seconds: float,
    ) -> ApprovalDecision:
        """Block until a human clicks approve/deny or the timeout expires."""
        pending = _PendingApproval(incident_id=incident_id)
        self._pending[incident_id] = pending

        pending.event.wait(timeout=timeout_seconds)

        self._pending.pop(incident_id, None)

        if pending.decision is not None:
            return pending.decision

        return ApprovalDecision(
            approved=False,
            decided_by="timeout",
            decided_at=datetime.now(timezone.utc),
            timed_out=True,
        )

    def _resolve(self, incident_id: str, approved: bool, user: str) -> None:
        pending = self._pending.get(incident_id)
        if not pending:
            # Slack load-balances interactions across every open Socket Mode
            # connection for the app, so a click can land on a process that is
            # not the one waiting. Say so instead of dropping it in silence.
            print(f"  [slack    ] got a decision for {incident_id} but this "
                  f"process has no approval pending for it — is another "
                  f"`python -m agent` / `serve` running?")
            return
        pending.decision = ApprovalDecision(
            approved=approved,
            decided_by=user,
            decided_at=datetime.now(timezone.utc),
        )
        pending.event.set()

    @staticmethod
    def _update_message(web_client, payload: dict, user: str, approved: bool) -> None:
        """Replace the buttons with a confirmation line."""
        channel = payload.get("channel", {}).get("id", "")
        ts = payload.get("message", {}).get("ts", "")
        if not channel or not ts:
            return

        verb = "Approved" if approved else "Denied"
        emoji = ":white_check_mark:" if approved else ":no_entry:"
        text = f"{emoji} *{verb}* by {user}"

        original_blocks = payload.get("message", {}).get("blocks", [])
        updated = [b for b in original_blocks if b.get("type") != "actions"]
        updated.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
        })

        try:
            web_client.chat_update(channel=channel, ts=ts, blocks=updated, text=text)
        except Exception:
            pass
