"""HTTP wiring for the on-call chat — SSE streaming plus session lookup.

Kept separate from api/chat.py: that module is the answering logic (pure
enough to unit-test without an HTTP server), this is the transport. GraphQL
handles structured queries; chat is a plain REST+SSE route because streaming
LLM tokens through a GraphQL subscription would mean a websocket transport
for one endpoint — SSE over a normal POST is the simpler, standard shape for
this and is what EventSource-style chat UIs expect.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.store import shared_chat_store
from api.chat import stream_answer

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


def _sse(event: str, data: str) -> str:
    # SSE data lines cannot contain a literal newline; escape it and let the
    # client un-escape, rather than losing multi-line answers.
    safe = data.replace("\\", "\\\\").replace("\n", "\\n")
    return f"event: {event}\ndata: {safe}\n\n"


@router.post("/chat")
def post_chat(payload: ChatRequest):
    """Streams the answer as SSE. First event carries the session id (minted
    if the client didn't send one) so the next turn can reuse it."""
    chat = shared_chat_store()
    session_id = chat.ensure_session(payload.session_id)

    def event_stream():
        yield _sse("session", session_id)
        try:
            for kind, text in stream_answer(session_id, payload.message):
                # "thinking" lets the UI show the model's reasoning trace as
                # a collapsible indicator; "delta" is the actual answer.
                event = "delta" if kind == "content" else "thinking"
                yield _sse(event, text)
        except Exception as exc:
            yield _sse("error", str(exc))
        yield _sse("done", "")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/chat/sessions")
def list_sessions():
    return {"sessions": shared_chat_store().list_sessions()}


@router.get("/chat/sessions/{session_id}")
def get_session(session_id: str):
    return {"messages": shared_chat_store().history(session_id, limit=100)}
