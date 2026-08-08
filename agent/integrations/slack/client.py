"""Thin wrapper over the Slack Web API — every call the integration needs."""
from __future__ import annotations

import os
from typing import Any, Optional


class SlackClient:
    def __init__(self) -> None:
        self._token = os.getenv("SLACK_BOT_TOKEN", "")
        self._client: Any = None
        self._channel_ids: dict[str, str] = {}

    def available(self) -> bool:
        if not self._token:
            return False
        try:
            from slack_sdk import WebClient
            self._client = WebClient(token=self._token)
            self._cache_channels()
            return True
        except ImportError:
            return False

    def _cache_channels(self) -> None:
        try:
            resp = self._client.conversations_list(
                types="public_channel,private_channel",
            )
            for ch in resp.get("channels", []):
                self._channel_ids[f"#{ch['name']}"] = ch["id"]
        except Exception:
            pass

    def _resolve(self, channel: str) -> str:
        if not channel.startswith("#"):
            return channel
        return self._channel_ids.get(channel, channel)

    def post_message(
        self,
        channel: str,
        blocks: list[dict],
        text: str = "",
        thread_ts: Optional[str] = None,
    ) -> Optional[str]:
        """Post a Block Kit message. Returns the message timestamp (thread root)."""
        if not self._client:
            return None
        try:
            resp = self._client.chat_postMessage(
                channel=self._resolve(channel),
                blocks=blocks,
                text=text or "Sentinel incident notification",
                thread_ts=thread_ts,
                unfurl_links=False,
                unfurl_media=False,
            )
            if ch_id := resp.get("channel"):
                self._channel_ids[channel] = ch_id
            return resp.get("ts")
        except Exception as e:
            print(f"  [slack    ] post failed ({channel}): {e}")
            return None

    def update_message(
        self,
        channel: str,
        ts: str,
        blocks: list[dict],
        text: str = "",
    ) -> bool:
        if not self._client:
            return False
        try:
            self._client.chat_update(
                channel=self._resolve(channel), ts=ts, blocks=blocks,
                text=text or "Sentinel update",
            )
            return True
        except Exception as e:
            print(f"  [slack    ] update failed ({channel}): {e}")
            return False

    def add_reaction(self, channel: str, ts: str, emoji: str) -> bool:
        if not self._client:
            return False
        try:
            self._client.reactions_add(
                channel=self._resolve(channel), timestamp=ts, name=emoji,
            )
            return True
        except Exception:
            return False

    def reply(
        self,
        channel: str,
        thread_ts: str,
        blocks: list[dict],
        text: str = "",
    ) -> Optional[str]:
        return self.post_message(channel, blocks, text, thread_ts=thread_ts)
