"""Actuator: pin a table back to its last known-good contents.

The blunt, reliable mitigation for corrupted data. It restores the table the RCA
blamed — which is normally a source table, not the feature that tripped the
assertion — and rebuilds everything derived from it. Restoring the feature table
alone would look like a fix until the next dbt run recomputed it from the same
bad source.
"""
from __future__ import annotations

from agent.contracts import ActionRecord, ActionType
from agent.registry import actuator
from agent.tools.actuators.base import LAST_GOOD, WarehouseActuator


@actuator
class PinFeatureActuator(WarehouseActuator):
    name = "pin_feature"
    action_type = ActionType.PIN_FEATURE

    def _mutate(self, table: str, action: ActionRecord) -> str:
        label = action.params.get("restore_label", LAST_GOOD)
        if not self.snapshots.exists(table, label):
            raise RuntimeError(
                f"no '{label}' snapshot of {table} to pin to — run "
                f"`python -m scenarios snapshot` while the pipeline is healthy"
            )
        before = self.snapshots.row_count(table)
        if not self.snapshots.restore(table, label):
            raise RuntimeError(f"restore of {table} from '{label}' failed")
        after = self.snapshots.row_count(table)
        return f"pinned {table} to {label} ({before} -> {after} rows)"
