"""Conversation memory for the on-call chat — durable, not per-request.

A chat turn is append-only within a session (a message, once sent, never
changes) but a session itself is a growing, queryable thing: "show me my last
five conversations", "load this session's history". That is closer to the
incident store's shape than the action journal's, so this gets its own SQLite
file rather than a JSONL log or, worse, only living in server memory — a
restarted API process should not erase what the on-call engineer already asked.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / ".sentinel" / "chat.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    title      TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,   -- user | assistant
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatStore:
    def __init__(self, path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    # --- writing ------------------------------------------------------ #
    def create_session(self, title: str = "") -> str:
        session_id = uuid.uuid4().hex[:12]
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, title, _now(), _now()),
            )
        return session_id

    def ensure_session(self, session_id: Optional[str]) -> str:
        """Reuse an existing session id, or mint one if none was given."""
        if session_id:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
            if row:
                return session_id
        return self.create_session()

    def add_message(self, session_id: str, role: str, content: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, role, content, _now()),
            )
            # First user message becomes the session title, so a sessions
            # list reads like conversation subjects rather than opaque ids.
            row = conn.execute(
                "SELECT title FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            title = (row["title"] if row else "") or ""
            if role == "user" and not title:
                conn.execute(
                    "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                    (content[:80], _now(), session_id),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (_now(), session_id),
                )

    # --- reading -------------------------------------------------------- #
    def history(self, session_id: str, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def list_sessions(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM sessions "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


_instance: Optional[ChatStore] = None


def shared_chat_store() -> ChatStore:
    global _instance
    if _instance is None:
        _instance = ChatStore()
    return _instance
