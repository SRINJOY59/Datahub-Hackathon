"""The action journal — every change the agent makes, with the way to undo it.

This is the safety net the whole autonomy story rests on. Before an action is
applied it is written here together with its inverse, so a rollback does not
depend on the agent still being alive: a crash mid-incident leaves a file on disk
that fully describes how to get back.

It is append-only JSON Lines at .sentinel/journal.jsonl, which makes it three
things at once — the rollback log, the immutable audit trail, and the input to
the shadow-mode savings digest ("this week I would have resolved N incidents").
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from agent.contracts import ActionRecord, ActionType

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JOURNAL = REPO_ROOT / ".sentinel" / "journal.jsonl"

# status values an entry can carry
APPLIED = "applied"
SIMULATED = "simulated"     # shadow mode: planned and costed, never executed
REVERTED = "reverted"
FAILED = "failed"


class ActionJournal:
    """Append-only record of actions and their inverses."""

    def __init__(self, path: Path | str = DEFAULT_JOURNAL) -> None:
        self.path = Path(path)

    # --- writing ---------------------------------------------------------- #
    def append(self, action: ActionRecord) -> ActionRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_to_dict(action)) + "\n")
        return action

    def record_applied(self, action: ActionRecord, incident_id: str) -> ActionRecord:
        action.incident_id = incident_id
        action.status = APPLIED
        action.applied_at = action.applied_at or datetime.now(timezone.utc)
        return self.append(action)

    def record_simulated(self, action: ActionRecord, incident_id: str) -> ActionRecord:
        """Shadow mode: what we *would* have done. Never executed."""
        action.incident_id = incident_id
        action.status = SIMULATED
        return self.append(action)

    def record_failed(self, action: ActionRecord, incident_id: str, error: str) -> ActionRecord:
        action.incident_id = incident_id
        action.status = FAILED
        action.note = (action.note + f" | failed: {error}").strip(" |")
        return self.append(action)

    def record_reverted(self, action: ActionRecord) -> ActionRecord:
        reverted = ActionRecord(
            action_type=action.action_type,
            target=action.target,
            params=dict(action.params),
            applied_at=datetime.now(timezone.utc),
            note=f"reverted {action.action_type.value}",
            incident_id=action.incident_id,
            status=REVERTED,
        )
        return self.append(reverted)

    # --- reading ---------------------------------------------------------- #
    def entries(self) -> list[ActionRecord]:
        if not self.path.exists():
            return []
        out: list[ActionRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(_from_dict(json.loads(line)))
            except (ValueError, KeyError):
                continue  # a torn final line must not make the journal unreadable
        return out

    def for_incident(self, incident_id: str) -> list[ActionRecord]:
        return [e for e in self.entries() if e.incident_id == incident_id]

    def applied_for_incident(self, incident_id: str) -> list[ActionRecord]:
        """Actions still in effect: applied and not since reverted."""
        entries = self.for_incident(incident_id)
        reverted = {(e.action_type, e.target) for e in entries if e.status == REVERTED}
        return [e for e in entries
                if e.status == APPLIED and (e.action_type, e.target) not in reverted]

    # --- rollback --------------------------------------------------------- #
    def undo_all(self, incident_id: str,
                 undo: Callable[[ActionRecord], bool],
                 only: Optional[Callable[[ActionRecord], bool]] = None
                 ) -> tuple[int, int]:
        """Replay the inverses of everything still applied for this incident, in
        reverse order. Returns (reverted, failed).

        Reverse order matters: actions were applied as a sequence that may depend
        on each other, so unwinding has to run backwards, like a stack.

        `only` narrows what gets undone. The caller uses it to keep protective
        actions in place while withdrawing the ones that changed data — a failed
        repair is a reason to keep the circuit breaker closed, not to open it.
        """
        ok = failed = 0
        for action in reversed(self.applied_for_incident(incident_id)):
            if only is not None and not only(action):
                continue
            try:
                if undo(action):
                    self.record_reverted(action)
                    ok += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        return ok, failed


# --------------------------------------------------------------------------- #
# (de)serialisation — ActionRecord is recursive via `inverse`
# --------------------------------------------------------------------------- #
def _to_dict(a: Optional[ActionRecord]) -> Optional[dict]:
    if a is None:
        return None
    return {
        "action_type": a.action_type.value,
        "target": a.target,
        "params": a.params,
        "inverse": _to_dict(a.inverse),
        "applied_at": a.applied_at.isoformat() if a.applied_at else None,
        "note": a.note,
        "incident_id": a.incident_id,
        "status": a.status,
    }


def _from_dict(d: Optional[dict]) -> Optional[ActionRecord]:
    if d is None:
        return None
    applied = d.get("applied_at")
    return ActionRecord(
        action_type=ActionType(d["action_type"]),
        target=d["target"],
        params=d.get("params") or {},
        inverse=_from_dict(d.get("inverse")),
        applied_at=datetime.fromisoformat(applied) if applied else None,
        note=d.get("note", ""),
        incident_id=d.get("incident_id", ""),
        status=d.get("status", "planned"),
    )
