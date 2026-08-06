"""Core LLM client for Sentinel.

A thin, provider-swappable wrapper over any OpenAI-compatible chat API. Defaults
to OpenRouter (set OPENROUTER_API_KEY). Point it elsewhere by changing base_url
and the key/env — the rest of the agent only depends on `complete()`.

Env:
    OPENROUTER_API_KEY   required to make real calls
    OPENROUTER_MODEL     model slug (default: anthropic/claude-3.5-sonnet)
    OPENROUTER_BASE_URL  override the endpoint (default OpenRouter)
"""
from __future__ import annotations

import os
import time
from typing import Optional

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-3.5-sonnet"


class LLMClient:
    """Minimal chat-completion client. `available()` is False when no API key is
    configured, so callers can fall back gracefully instead of crashing."""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
        self.base_url = base_url or os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL)
        self._client = self._build_client() if self.api_key else None

    def _build_client(self):
        from openai import OpenAI

        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            default_headers={"X-Title": "Sentinel"},  # shows up in OpenRouter logs
        )

    def available(self) -> bool:
        return self._client is not None

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
        retries: int = 3,
    ) -> str:
        """Single-turn completion, with retries for transient free-tier blips.

        Raises RuntimeError if no key is configured or all attempts fail.
        """
        if not self._client:
            raise RuntimeError(
                "LLMClient has no API key. Set OPENROUTER_API_KEY to enable LLM calls."
            )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                choices = resp.choices
                if not choices:  # free-tier error payload arrives as empty choices
                    raise RuntimeError("no choices returned")
                msg = choices[0].message
                # reasoning models sometimes leave content empty; fall back to it
                content = (msg.content or getattr(msg, "reasoning", "") or "").strip()
                if content:
                    return content
                raise RuntimeError("empty completion")
            except Exception as e:
                last_err = e
                if attempt < retries - 1:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"LLM call failed after {retries} attempts: {last_err}")
