"""Shared machinery for actuators.

Every actuator answers the same two questions — do the thing, and undo the thing
— so the parts that are easy to get subtly wrong live here rather than being
retyped six times:

  * an action always comes back with its inverse populated, because an action
    without a recorded inverse is an action nobody can roll back;
  * warehouse actuators snapshot what they are about to change *before* changing
    it, so the inverse restores the exact state the incident was in rather than
    some earlier idea of "good";
  * anything that rewrites a table rebuilds the models downstream of it, since
    leaving stale derived tables behind would make the validation gate judge the
    wrong data.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from agent.contracts import ActionRecord, ActionType
from agent.tools.warehouse.dbt_runner import DbtRunner
from agent.tools.warehouse.snapshots import SnapshotStore

LAST_GOOD = "last_good"


class BaseActuator(ABC):
    """One reversible mitigation."""

    name: str = ""
    action_type: ActionType

    @abstractmethod
    def _apply(self, action: ActionRecord) -> ActionRecord:
        """Perform the action and return the ActionRecord that undoes it."""

    @abstractmethod
    def _revert(self, inverse: ActionRecord) -> bool:
        """Perform the recorded inverse."""

    # ------------------------------------------------------------------ #
    def apply(self, action: ActionRecord) -> ActionRecord:
        inverse = self._apply(action)
        action.inverse = inverse
        action.applied_at = datetime.now(timezone.utc)
        return action

    def revert(self, action: ActionRecord) -> bool:
        if action.inverse is None:
            return False
        return self._revert(action.inverse)


class WarehouseActuator(BaseActuator):
    """An actuator that rewrites warehouse tables.

    Subclasses get snapshot-then-mutate-then-rebuild for free; they only supply
    the mutation itself.
    """

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.snapshots = SnapshotStore()
        self.dbt = DbtRunner()

    # ------------------------------------------------------------------ #
    @abstractmethod
    def _mutate(self, table: str, action: ActionRecord) -> str:
        """Change `table` in place. Return a human description of what changed."""

    def _apply(self, action: ActionRecord) -> ActionRecord:
        table = action.params.get("table")
        if not table:
            raise ValueError(f"{self.name}: no target table in action params")

        # The restore point is per-action, not per-incident. Two warehouse
        # actuators in one plan both snapshot the same table, and a shared label
        # would mean the second overwrote the first's way back — the rollback
        # would then quietly restore an intermediate state and lose whatever the
        # earlier action had moved aside.
        restore_point = f"pre_{action.incident_id or 'manual'}_{self.action_type.value}"
        if not self.snapshots.capture(table, restore_point):
            raise RuntimeError(f"{self.name}: could not snapshot {table}; "
                               f"refusing to act without a way back")

        action.note = (action.note + " | " + self._mutate(table, action)).strip(" |")
        self._rebuild()

        return ActionRecord(
            action_type=self.action_type,
            target=action.target,
            params={"table": table, "restore_label": restore_point},
            note=f"restore {table} to its pre-{self.action_type.value} state",
            incident_id=action.incident_id,
        )

    def _revert(self, inverse: ActionRecord) -> bool:
        table = inverse.params.get("table")
        label = inverse.params.get("restore_label")
        if not (table and label):
            return False
        if not self.snapshots.restore(table, label):
            return False
        self._rebuild()
        return True

    def _rebuild(self) -> None:
        """Recompute everything derived from the table we just changed."""
        self.dbt.run(quiet=True)
