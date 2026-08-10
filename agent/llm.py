"""Core LLM client with Adaptive Model Routing for Sentinel.

Dynamically routes queries to optimal models based on task complexity:
- TaskType.CODE: Fast coding specialist (cohere/north-mini-code, qwen-coder) for instant patch synthesis.
- TaskType.REASONING: High-capacity reasoning models (nemotron-3-ultra, claude-3.5-sonnet) for deep causality.
- TaskType.CHAT: Interactive streaming models (gemma-4-31b-it) for on-call assistant.
- TaskType.FAST: Lightweight low-latency models (nemotron-nano-9b-v2) for metadata tagging.

Supports automatic failover chains: if a model hits rate limits or 404s, it degrades gracefully to secondary models.
"""
from __future__ import annotations

import json
import os
import time
from enum import Enum
from typing import Iterator, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_FALLBACK_MODEL = "cohere/north-mini-code:free"


class TaskType(str, Enum):
    CODE = "code"            # Code synthesis, patch generation, syntax migrations
    REASONING = "reasoning"  # Deep root-cause analysis, blast radius, graph causality
    CHAT = "chat"            # Interactive conversational SRE assistant
    FAST = "fast"            # Lightweight classification, metadata extraction


class ModelRouter:
    """Dynamically resolves the optimal model chain for a given task complexity."""

    @staticmethod
    def get_models_for_task(task_type: TaskType | str) -> list[str]:
        """Returns a prioritized list of models for the task (primary + fallbacks)."""
        t = TaskType(task_type) if isinstance(task_type, str) else task_type
        default_model = os.getenv("OPENROUTER_MODEL", DEFAULT_FALLBACK_MODEL)

        if t == TaskType.CODE:
            primary = os.getenv("OPENROUTER_MODEL_CODE", "cohere/north-mini-code:free")
            fallbacks = ["nvidia/nemotron-nano-9b-v2:free", "google/gemma-4-31b-it:free", default_model]
        elif t == TaskType.REASONING:
            primary = os.getenv("OPENROUTER_MODEL_REASONING", "nvidia/nemotron-3-ultra-550b-a55b:free")
            fallbacks = ["google/gemma-4-31b-it:free", "cohere/north-mini-code:free", default_model]
        elif t == TaskType.CHAT:
            primary = os.getenv("OPENROUTER_MODEL_CHAT", "google/gemma-4-31b-it:free")
            fallbacks = ["cohere/north-mini-code:free", "nvidia/nemotron-nano-9b-v2:free", default_model]
        else:  # FAST
            primary = os.getenv("OPENROUTER_MODEL_FAST", "nvidia/nemotron-nano-9b-v2:free")
            fallbacks = ["cohere/north-mini-code:free", default_model]

        # Deduplicate while preserving priority order
        seen = set()
        chain = []
        for m in [primary] + fallbacks:
            if m and m not in seen:
                seen.add(m)
                chain.append(m)
        return chain

    @staticmethod
    def infer_task_type(prompt: str, system: Optional[str] = None) -> TaskType:
        """Heuristically infer task complexity from prompt and system instructions."""
        text = f"{system or ''} {prompt}".lower()
        if any(k in text for k in ["file:", "rewrite", "diff", "code fix", "def ", "class ", "import ", "syntax", "migration"]):
            return TaskType.CODE
        if any(k in text for k in ["root cause", "rca", "causality", "investigate", "post-mortem", "blast radius"]):
            return TaskType.REASONING
        if any(k in text for k in ["chat", "assistant", "ask on-call", "conversation"]):
            return TaskType.CHAT
        return TaskType.FAST


class LLMClient:
    """Adaptive chat-completion client with multi-tier routing and failover."""

    def __init__(
        self,
        model: Optional[str] = None,
        task_type: Optional[TaskType | str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.task_type = TaskType(task_type) if isinstance(task_type, str) else task_type
        self.explicit_model = model
        self.base_url = base_url or os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL)
        self._client = self._build_client() if self.api_key else None

    @classmethod
    def for_task(cls, task_type: TaskType | str, **kwargs) -> LLMClient:
        """Instantiate an LLMClient tuned for a specific task complexity."""
        return cls(task_type=task_type, **kwargs)

    @property
    def model(self) -> str:
        """Active model name (either explicit or routed for task)."""
        if self.explicit_model:
            return self.explicit_model
        chain = ModelRouter.get_models_for_task(self.task_type or TaskType.FAST)
        return chain[0] if chain else DEFAULT_FALLBACK_MODEL

    def _build_client(self):
        from openai import OpenAI

        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            default_headers={"X-Title": "Sentinel"},
        )

    def available(self) -> bool:
        return self._client is not None

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
        retries: int = 2,
    ) -> str:
        """Single-turn completion with adaptive model routing and automatic failover."""
        if not self._client:
            raise RuntimeError(
                "LLMClient has no API key. Set OPENROUTER_API_KEY to enable LLM calls."
            )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # Resolve model chain
        if self.explicit_model:
            model_chain = [self.explicit_model]
        else:
            task = self.task_type or ModelRouter.infer_task_type(prompt, system)
            model_chain = ModelRouter.get_models_for_task(task)

        last_err: Optional[Exception] = None

        for model_slug in model_chain:
            for attempt in range(retries):
                try:
                    resp = self._client.chat.completions.create(
                        model=model_slug,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    choices = resp.choices
                    if not choices:
                        raise RuntimeError("no choices returned")
                    msg = choices[0].message
                    content = (msg.content or getattr(msg, "reasoning", "") or "").strip()
                    if content:
                        return content
                    raise RuntimeError("empty completion")
                except Exception as e:
                    last_err = e
                    if attempt < retries - 1:
                        time.sleep(1.0 * (attempt + 1))
            # Failed on this model slug, failover to next model in chain

        raise RuntimeError(f"LLM call failed across models {model_chain}: {last_err}")

    def stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 800,
    ) -> Iterator[tuple[str, str]]:
        """Yield (kind, text) deltas as they arrive for chat UIs with failover."""
        if not self._client:
            raise RuntimeError(
                "LLMClient has no API key. Set OPENROUTER_API_KEY to enable LLM calls."
            )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        if self.explicit_model:
            model_chain = [self.explicit_model]
        else:
            task = self.task_type or ModelRouter.infer_task_type(prompt, system)
            model_chain = ModelRouter.get_models_for_task(task)

        last_err: Optional[Exception] = None
        for model_slug in model_chain:
            try:
                response = self._client.chat.completions.create(
                    model=model_slug,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
                yielded_any = False
                for chunk in response:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    content = getattr(delta, "content", None)
                    reasoning = getattr(delta, "reasoning", None)
                    if content:
                        yielded_any = True
                        yield "content", content
                    elif reasoning:
                        yielded_any = True
                        yield "reasoning", reasoning
                if yielded_any:
                    return
            except Exception as e:
                last_err = e
                continue

        if last_err:
            raise RuntimeError(f"Streaming failed across models {model_chain}: {last_err}")

    def structured(
        self,
        prompt: str,
        schema: Type[M],
        system: Optional[str] = None,
        max_tokens: int = 1000,
        retries: int = 2,
    ) -> Optional[M]:
        """Return a validated `schema` instance with adaptive routing and extraction fallback."""
        if not self._client:
            return None

        sys_msg = (system or "You are precise.") + (
            " Respond with ONLY a single JSON object matching the requested schema. "
            "No prose, no markdown, no reasoning outside the JSON."
        )
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt + "\n\nJSON schema:\n"
             + json.dumps(schema.model_json_schema())},
        ]

        if self.explicit_model:
            model_chain = [self.explicit_model]
        else:
            task = self.task_type or ModelRouter.infer_task_type(prompt, system)
            model_chain = ModelRouter.get_models_for_task(task)

        formats = [
            {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "strict": True,
                "schema": schema.model_json_schema()}},
            {"type": "json_object"},
            None,
        ]

        for model_slug in model_chain:
            for attempt in range(retries):
                fmt = formats[min(attempt, len(formats) - 1)]
                try:
                    kwargs = dict(model=model_slug, messages=messages,
                                  temperature=0.1, max_tokens=max_tokens)
                    if fmt is not None:
                        kwargs["response_format"] = fmt
                    resp = self._client.chat.completions.create(**kwargs)
                    if not resp.choices:
                        raise RuntimeError("no choices")
                    msg = resp.choices[0].message
                    content = (msg.content or getattr(msg, "reasoning", "") or "")
                    data = _extract_json(content)
                    if data is None:
                        raise RuntimeError("no JSON object in response")
                    return schema.model_validate(data)
                except (ValidationError, Exception):
                    if attempt < retries - 1:
                        time.sleep(1.0 * (attempt + 1))
        return None


def _extract_json(text: str) -> Optional[dict]:
    """Pull the last complete top-level JSON object out of text (handles
    reasoning models that emit prose then JSON)."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    starts = [i for i, ch in enumerate(text) if ch == "{"]
    for start in reversed(starts):
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
    return None

