"""Ask-the-on-call — a chat assistant grounded in the incident store.

Retrieval here is SQL LIKE over keywords extracted from the question, unioned
with the most recent incidents. That is a plain, honest choice: the roadmap
still lists vector memory as unbuilt, and a keyword+recency join over a local
SQLite table is what "grounded, not hallucinated" actually looks like at this
scale — dressing it up as semantic search would overclaim what it does.

Conversation memory is real: every turn is persisted to ChatStore, and the
next turn's prompt includes prior turns from the same session, not just the
latest message.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional

from agent.llm import LLMClient
from agent.store import shared_chat_store, shared_store

_STOPWORDS = {
    "what", "when", "where", "which", "about", "happened", "incident",
    "incidents", "with", "this", "that", "have", "were", "been", "from",
    "cost", "much", "many", "there", "does", "doing", "should", "would",
    "could", "tell", "show", "give", "recent", "latest",
}

SYSTEM_PROMPT = (
    "You are Sentinel's on-call assistant. Sentinel is an autonomous agent "
    "that detects, diagnoses, and remediates data/ML pipeline incidents.\n\n"
    "Answer ONLY from the INCIDENT CONTEXT provided in the prompt. If the "
    "context does not contain enough information to answer, say so plainly — "
    "do not guess or invent an incident, asset, or number.\n\n"
    "When you reference an incident, cite its id (e.g. INC-2130) so the "
    "reader can look it up. Answer directly and concisely — do not narrate "
    "your reasoning process or think out loud before answering."
)


def _extract_keywords(question: str) -> list[str]:
    words = re.findall(r"[a-zA-Z_]{4,}", question.lower())
    return [w for w in words if w not in _STOPWORDS][:6]


def gather_context(question: str, limit: int = 8) -> list[dict]:
    store = shared_store()
    recent = store.list(limit=5)
    keywords = _extract_keywords(question)
    hits = store.search(keywords, limit=limit) if keywords else []

    seen: dict[str, dict] = {}
    for row in hits + recent:
        seen.setdefault(row["id"], row)
    ordered = sorted(seen.values(), key=lambda r: r["detected_at"], reverse=True)
    return ordered[:limit]


def format_context(rows: list[dict]) -> str:
    if not rows:
        return "(no incidents recorded yet)"
    lines = []
    for r in rows:
        cost = f"${r['cost_usd']:,.0f}" if r.get("cost_usd") else "n/a"
        actions = ", ".join(r.get("actions") or []) or "none"
        lines.append(
            f"- {r['id']} [{r['status']}] {r.get('asset_name') or r['asset_urn']}: "
            f"{r.get('change_type') or 'unknown'} (confidence {r.get('confidence')}, "
            f"tier {r.get('tier')}). {r.get('narrative') or r.get('summary') or ''} "
            f"Actions: {actions}. Cost exposure: {cost}. "
            f"Detected: {r['detected_at']}, closed: {r.get('closed_at') or 'still open'}."
        )
    return "\n".join(lines)


def _build_prompt(session_id: str, question: str) -> str:
    chat = shared_chat_store()
    rows = gather_context(question)
    context = format_context(rows)

    history = chat.history(session_id, limit=10)
    prior = history[:-1] if history and history[-1]["role"] == "user" else history
    convo = "\n".join(f"{h['role']}: {h['content']}" for h in prior) or "(none yet)"

    return (
        f"INCIDENT CONTEXT:\n{context}\n\n"
        f"CONVERSATION SO FAR:\n{convo}\n\n"
        f"QUESTION: {question}"
    )


def stream_answer(session_id: str, question: str,
                  llm: Optional[LLMClient] = None) -> Iterator[tuple[str, str]]:
    """Persists the user turn, streams (kind, text) deltas, persists the
    assistant turn — content only, never the model's reasoning trace.

    Assumes session_id already exists — the caller resolves/creates it so it
    can report the id to the client before the first token arrives.
    """
    chat = shared_chat_store()
    chat.add_message(session_id, "user", question)

    llm = llm or LLMClient()
    if not llm.available():
        context = format_context(gather_context(question))
        msg = (
            "LLM is not configured (set OPENROUTER_API_KEY) — here is the raw "
            f"incident data I would have answered from:\n\n{context}"
        )
        chat.add_message(session_id, "assistant", msg)
        yield "content", msg
        return

    prompt = _build_prompt(session_id, question)
    answer_parts: list[str] = []
    try:
        for kind, text in llm.stream(prompt, system=SYSTEM_PROMPT, max_tokens=600):
            if kind == "content":
                answer_parts.append(text)
            yield kind, text
    finally:
        answer = "".join(answer_parts).strip()
        if answer:
            chat.add_message(session_id, "assistant", answer)
