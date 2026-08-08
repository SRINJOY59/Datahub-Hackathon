"""How much the agent is allowed to do on its own.

The useful question is not "is acting safe" — every action the agent can take is
journaled with its inverse and followed by a validation gate that rolls back on
failure, so the downside is bounded by construction. The real question is "is it
safe to act *without telling anyone*", and that depends on what the asset is and
how sure we are.

So actions are split by what they touch:

  protective  tag downstream, pause a consumer. These only ever reduce harm —
              they stop people and jobs using data we believe is bad. Withholding
              them while waiting for a human is itself the risky choice, so they
              run at every tier.
  mutating    pin, quarantine, dedupe, repoint. These change data or what is
              serving. Reversible, but they need confidence behind them.

and the tier decides which of those two the agent may use, and whether a human
has to be brought in regardless.
"""
from __future__ import annotations

from agent.contracts import (
    PROTECTIVE_ACTIONS,
    ActionType,
    AutonomyTier,
    ContextBundle,
    RootCauseAnalysis,
    is_protective,
)

PII_TAG = "PII"
CRITICAL_TAG = "Tier-Critical"

# Past this many downstream consumers, a human reviews the permanent fix even if
# the agent mitigates immediately.
WIDE_BLAST_RADIUS = 3


class AutonomyPolicy:
    """Decides the tier, and enforces it by filtering the plan."""

    def tier(self, context: ContextBundle,
             rca: RootCauseAnalysis | None = None) -> AutonomyTier:
        tags = set(context.tags or [])
        confidence = (rca.confidence if rca else "low") or "low"

        # Sensitive data plus an uncertain diagnosis is the one combination where
        # guessing is worse than waiting: protect, and page someone.
        if PII_TAG in tags and confidence != "high":
            return AutonomyTier.HUMAN_ONLY

        if (CRITICAL_TAG in tags
                or PII_TAG in tags
                or confidence == "low"
                or len(context.downstream) > WIDE_BLAST_RADIUS):
            return AutonomyTier.PR_ONLY

        return AutonomyTier.AUTO

    # ------------------------------------------------------------------ #
    @staticmethod
    def permits(tier: AutonomyTier, action_type: ActionType) -> bool:
        if tier is AutonomyTier.HUMAN_ONLY:
            return action_type in PROTECTIVE_ACTIONS
        return True

    def filter(self, tier: AutonomyTier, actions: list) -> tuple[list, list]:
        """Split a plan into what may run now and what is being withheld."""
        allowed, withheld = [], []
        for action in actions:
            (allowed if self.permits(tier, action.action_type) else withheld
             ).append(action)
        return allowed, withheld

    @staticmethod
    def needs_human(tier: AutonomyTier) -> bool:
        """Should a fix PR be opened and the owners told, even on success?"""
        return tier in (AutonomyTier.PR_ONLY, AutonomyTier.HUMAN_ONLY)

    # kept as a method so callers holding a policy can classify without a second
    # import; the single definition lives in contracts.
    is_protective = staticmethod(is_protective)

    @staticmethod
    def is_containment_only(actions: list) -> bool:
        """True when a plan can only limit the damage, never repair it.

        Some incidents are outside the agent's reach by nature: a feed that
        stopped delivering cannot be restored from a snapshot, because the rows
        never existed. For those the validation gate stays red no matter what the
        agent does, and treating that as a failed mitigation would be wrong — the
        agent did everything available to it.
        """
        return bool(actions) and all(
            a.action_type in PROTECTIVE_ACTIONS for a in actions
        )

    @staticmethod
    def explain(tier: AutonomyTier, context: ContextBundle,
                rca: RootCauseAnalysis | None) -> str:
        confidence = (rca.confidence if rca else "unknown")
        tags = ", ".join(context.tags) or "no governance tags"
        if tier is AutonomyTier.HUMAN_ONLY:
            return (f"{tags}; confidence {confidence} — protective actions only, "
                    f"paging owners")
        if tier is AutonomyTier.PR_ONLY:
            return (f"{tags}; confidence {confidence}; "
                    f"{len(context.downstream)} downstream — mitigate now, "
                    f"human reviews the permanent fix")
        return f"{tags}; confidence {confidence} — full autonomy"
