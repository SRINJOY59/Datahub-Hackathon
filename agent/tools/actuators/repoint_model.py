"""Actuator: move the `champion` alias off a bad model version.

The fastest mitigation there is — no retraining, no data movement, just a pointer
change that takes effect on the next scoring run, and is undone by pointing it
back.

Only versions explicitly tagged `validation_status=passed` with metrics inside
the healthy band are eligible. Rolling back to whatever happened to be previous
would eventually roll back onto another broken model; a rollback target has to
have earned it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agent.contracts import ActionRecord, ActionType
from agent.registry import actuator
from agent.tools.actuators.base import BaseActuator
from agent.tools.warehouse.champion import ChampionMetrics


@actuator
class RepointModelActuator(BaseActuator):
    name = "repoint_model"
    action_type = ActionType.REPOINT_MODEL

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.champion = ChampionMetrics()

    def _apply(self, action: ActionRecord) -> ActionRecord:
        current = self.champion.current()
        if current is None:
            raise RuntimeError("no champion model registered — nothing to repoint")

        target_version = action.params.get("to_version")
        if not target_version:
            last_good = self.champion.last_good(exclude_version=current.version)
            if last_good is None:
                raise RuntimeError(
                    f"no validated healthy version to roll back to "
                    f"(champion is v{current.version}); every registered version "
                    f"is either unvalidated or outside the healthy metric band"
                )
            target_version = last_good.version

        if target_version == current.version:
            raise RuntimeError(f"champion is already v{current.version}")

        # Score the candidate before promoting it. Finding out how a rollback
        # target behaves by pointing production at it and watching is not an
        # experiment, and the before/after is what makes the action reviewable.
        preview = self._preview(current.version, target_version)

        if not self.champion.set_alias(target_version):
            raise RuntimeError(f"could not move the alias to v{target_version}")

        action.note = (action.note + f" | champion v{current.version} -> "
                                     f"v{target_version}"
                       + (f" | shadow: {preview}" if preview else "")).strip(" |")
        return ActionRecord(
            action_type=self.action_type,
            target=action.target,
            params={"to_version": current.version},
            note=f"restore champion to v{current.version}",
            incident_id=action.incident_id,
        )

    def _revert(self, inverse: ActionRecord) -> bool:
        version = inverse.params.get("to_version")
        if not version:
            return False
        inverse.applied_at = datetime.now(timezone.utc)
        return self.champion.set_alias(version)

    @staticmethod
    def _preview(current: str, candidate: str) -> str:
        """A read-only comparison of the two versions on identical data. Never
        allowed to block the rollback: if the preview cannot be produced, the
        mitigation is still the right thing to do."""
        try:
            from agent.tools.warehouse.shadow import ShadowEnvironment

            result = ShadowEnvironment().compare_versions(current, candidate)
            return result.note if result.passed else ""
        except Exception:
            return ""
