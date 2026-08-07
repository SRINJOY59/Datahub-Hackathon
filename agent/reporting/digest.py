"""What the agent did, or would have done, expressed in hours.

Nobody adopts an autonomous agent on day one. They run it in shadow mode first,
watch what it *would* have done for a week, and decide whether they believe it.
This turns the action journal into that argument: how many incidents it caught,
what it proposed, and roughly how much on-call time that represents.

The hour estimates below are deliberately conservative and deliberately visible.
They are the weakest numbers in this system — a guess at what the work would have
cost a human — so they are stated as assumptions rather than buried as facts, and
the digest always reports incident counts alongside them.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from agent.contracts import ActionType
from agent.journal import APPLIED, FAILED, SIMULATED, ActionJournal

# Hours of human time a mitigation of this kind typically displaces: noticing,
# diagnosing, deciding, doing it by hand, and verifying it worked.
HOURS_SAVED: dict[ActionType, float] = {
    ActionType.PIN_FEATURE: 2.0,
    ActionType.QUARANTINE: 2.5,
    ActionType.DEDUPE_PARTITION: 1.5,
    ActionType.REPOINT_MODEL: 1.0,
    ActionType.TAG_ASSET: 0.25,
    ActionType.PAUSE_JOB: 0.5,
}
DEFAULT_HOURS = 0.5


@dataclass
class Digest:
    incidents: int = 0
    actions_applied: int = 0
    actions_simulated: int = 0
    actions_failed: int = 0
    hours_saved: float = 0.0
    by_action: dict[str, int] = field(default_factory=dict)
    incidents_by_id: list[str] = field(default_factory=list)

    @property
    def shadow_mode(self) -> bool:
        return self.actions_simulated > 0 and self.actions_applied == 0

    def render(self) -> str:
        verb = "would have taken" if self.shadow_mode else "took"
        counted = self.actions_simulated if self.shadow_mode else self.actions_applied
        lines = [
            "",
            "=== Sentinel digest ===",
            f"  incidents handled : {self.incidents}",
            f"  actions {verb:16s}: {counted}",
        ]
        if self.actions_failed:
            lines.append(f"  actions failed    : {self.actions_failed}")
        for name, count in sorted(self.by_action.items(), key=lambda kv: -kv[1]):
            lines.append(f"      {name:20s} {count}")
        lines += [
            "",
            f"  estimated on-call time saved: ~{self.hours_saved:.1f} hours",
            "  (an estimate from the per-action table in agent/reporting/digest.py,",
            "   not a measurement — the incident count above is the hard number)",
        ]
        if self.shadow_mode:
            lines += [
                "",
                "  SHADOW MODE: nothing was applied. This is what the agent would",
                "  have done if it had been allowed to act.",
            ]
        if self.incidents_by_id:
            lines.append(f"\n  incidents: {', '.join(self.incidents_by_id)}")
        return "\n".join(lines)


class SavingsDigest:
    """Aggregates the action journal into something a human can act on."""

    def __init__(self, journal: ActionJournal | None = None) -> None:
        self.journal = journal or ActionJournal()

    def build(self) -> Digest:
        entries = self.journal.entries()
        digest = Digest()
        if not entries:
            return digest

        incidents: list[str] = []
        counts: Counter = Counter()

        for entry in entries:
            if entry.incident_id and entry.incident_id not in incidents:
                incidents.append(entry.incident_id)

            if entry.status == APPLIED:
                digest.actions_applied += 1
            elif entry.status == SIMULATED:
                digest.actions_simulated += 1
            elif entry.status == FAILED:
                digest.actions_failed += 1
                continue  # nothing was saved by an action that did not happen
            else:
                continue  # reverted entries are the undo half of a pair

            counts[entry.action_type.value] += 1
            digest.hours_saved += HOURS_SAVED.get(entry.action_type, DEFAULT_HOURS)

        digest.incidents = len(incidents)
        digest.incidents_by_id = incidents
        digest.by_action = dict(counts)
        return digest
