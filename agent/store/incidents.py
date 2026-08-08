"""The incident store — what happened, not just what was done.

The action journal is append-only and event-shaped, which is exactly right for
actions: an action and its inverse are facts that never change. An *incident* is
not that shape. It is an entity with a lifecycle — it is opened when the RCA
lands and closed minutes later with an outcome — so recording it needs an update,
not an append. Writing it once at the end would work only if nothing ever
crashed mid-incident and nobody ever wanted to see what is open right now.

Hence SQLite rather than another JSONL file:

  * an incident is mutable (open -> resolved/contained), and UPDATE says that
    honestly where append-and-fold only simulates it;
  * the webhook RunQueue is a real thread pool, so two incidents can close in
    the same instant. WAL mode makes that safe; a read-modify-write over a text
    file would not be;
  * the questions asked of this data are relational — filter by status, order by
    date, average the time to resolve — and those are one line of SQL each.

The journal is untouched and remains the audit trail and rollback source. This
sits beside it and is joined on incident_id; between them, "what did the agent
do" and "how did it end" are both answerable.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / ".sentinel" / "incidents.db"

OPEN = "open"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id                TEXT PRIMARY KEY,
    asset_urn         TEXT NOT NULL,
    asset_name        TEXT,
    signal_type       TEXT,
    summary           TEXT,
    change_type       TEXT,
    confidence        TEXT,
    narrative         TEXT,
    root_cause_asset  TEXT,
    root_cause_column TEXT,
    tier              TEXT,
    status            TEXT NOT NULL,
    resolved          INTEGER NOT NULL DEFAULT 0,
    pr                TEXT,
    cost_usd          REAL,
    cost_basis        TEXT,
    downstream_count  INTEGER,
    actions           TEXT,
    detected_at       TEXT NOT NULL,
    closed_at         TEXT,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_status   ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_detected ON incidents(detected_at);
CREATE INDEX IF NOT EXISTS idx_incidents_asset    ON incidents(asset_urn);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class IncidentStore:
    def __init__(self, path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._ensure_schema()

    # --- connection ------------------------------------------------------- #
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # A connection per operation rather than one shared across threads:
        # sqlite3 objects are not thread-safe, and the RunQueue is a thread pool.
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
            # WAL is a persistent property of the file; setting it once lets
            # readers (the dashboard) work while a run is writing.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    # --- writing ---------------------------------------------------------- #
    def open_incident(self, incident, context, rca) -> None:
        """Record the incident as soon as the diagnosis exists.

        Writing here rather than only at the end is what makes an in-flight or
        crashed incident visible instead of invisible.
        """
        row = {
            "id": incident.id,
            "asset_urn": incident.asset_urn,
            "asset_name": getattr(context, "name", None),
            "signal_type": _enum(incident.signal_type),
            "summary": incident.summary,
            "change_type": _enum(rca.change_type),
            "confidence": rca.confidence,
            "narrative": rca.narrative,
            "root_cause_asset": rca.root_cause_asset,
            "root_cause_column": rca.root_cause_column,
            "downstream_count": len(getattr(context, "downstream", []) or []),
            "status": OPEN,
            "detected_at": _iso(incident.detected_at) or _now(),
            "updated_at": _now(),
        }
        cols = ", ".join(row)
        placeholders = ", ".join(f":{k}" for k in row)
        # On conflict refresh the diagnosis but never the lifecycle fields —
        # re-opening must not silently un-close an incident.
        updates = ", ".join(
            f"{k}=excluded.{k}" for k in row
            if k not in ("id", "status", "detected_at")
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                f"INSERT INTO incidents ({cols}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                row,
            )

    def close_incident(self, incident, outcome, tier=None, cost=None) -> None:
        """Record how it ended."""
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE incidents SET
                    status = :status,
                    resolved = :resolved,
                    tier = COALESCE(:tier, tier),
                    pr = :pr,
                    cost_usd = :cost_usd,
                    cost_basis = :cost_basis,
                    actions = :actions,
                    closed_at = :closed_at,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                {
                    "id": incident.id,
                    "status": outcome.status,
                    "resolved": 1 if outcome.resolved else 0,
                    "tier": _enum(tier),
                    "pr": outcome.pr,
                    "cost_usd": getattr(cost, "dollars", None),
                    "cost_basis": getattr(cost, "basis", None),
                    "actions": json.dumps(outcome.actions_taken or []),
                    "closed_at": _now(),
                    "updated_at": _now(),
                },
            )

    # --- reading ---------------------------------------------------------- #
    def get(self, incident_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list(self, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM incidents"
        params: list = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def stats(self) -> dict:
        with self._connect() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*)                                   AS total,
                    SUM(resolved)                              AS resolved,
                    SUM(CASE WHEN status = 'open' THEN 1 END)  AS open,
                    SUM(cost_usd)                              AS exposure_usd,
                    AVG(CASE WHEN closed_at IS NOT NULL
                        THEN (julianday(closed_at) - julianday(detected_at))
                             * 24 * 60 END)                    AS mttr_minutes
                FROM incidents
                """
            ).fetchone()
            by_type = conn.execute(
                "SELECT change_type, COUNT(*) AS n FROM incidents "
                "GROUP BY change_type ORDER BY n DESC"
            ).fetchall()
        return {
            "total": totals["total"] or 0,
            "resolved": totals["resolved"] or 0,
            "open": totals["open"] or 0,
            "exposure_usd": totals["exposure_usd"] or 0.0,
            "mttr_minutes": totals["mttr_minutes"],
            "by_change_type": {r["change_type"] or "unknown": r["n"] for r in by_type},
        }

    def export(self) -> list[dict]:
        """Everything as JSON — a .db is not cat-able, so keep a way out."""
        return self.list(limit=10_000)


def _enum(value) -> Optional[str]:
    if value is None:
        return None
    return getattr(value, "value", str(value))


def _row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    if data.get("actions"):
        try:
            data["actions"] = json.loads(data["actions"])
        except (json.JSONDecodeError, TypeError):
            data["actions"] = []
    else:
        data["actions"] = []
    data["resolved"] = bool(data.get("resolved"))
    return data


_instance: Optional[IncidentStore] = None


def shared_store() -> IncidentStore:
    global _instance
    if _instance is None:
        _instance = IncidentStore()
    return _instance
