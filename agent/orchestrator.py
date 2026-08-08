"""Sentinel orchestrator — the closed remediation loop.

    detect -> context -> investigate -> recall -> RCA -> policy -> plan
           -> act (journaled) -> validate
                -> pass: resolve, write the post-mortem back to the graph
                -> fail: roll back through the journal, escalate to the owners

The loop itself stays deliberately thin. Deciding *what* to do lives in
RemediationPlanner, deciding *how much* the agent may do lives in AutonomyPolicy,
and doing it lives behind the Mechanisms interface — so this file reads as the
shape of the process rather than the details of any part of it.

The validation gate is the safety property that matters: nothing is declared
resolved until an independent check says the pipeline is actually healthy, and a
failed check triggers a real rollback rather than an apology.

Run:  python -m agent
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from agent.contracts import (
    ActionRecord,
    ActionType,
    AutonomyTier,
    ChangeType,
    ContextBundle,
    CostEstimate,
    Incident,
    IncidentOutcome,
    Mechanisms,
    MemoryStore,
    PostMortem,
    RootCauseAnalysis,
)
from agent.llm import LLMClient
from agent.planner import RemediationPlanner
from agent.policy import AutonomyPolicy
from agent.rca import RCAEngine
from agent.reporting.cost import CostEstimator
from agent.tools.graph.urns import short_name

# Incidents whose fix is a code change, not a data or model action.
_CODE_CHANGES = (ChangeType.DEPENDENCY_CHANGE, ChangeType.CODE_CHANGE)


def log(stage: str, msg: str) -> None:
    print(f"  [{stage:9s}] {msg}")


class SentinelAgent:
    def __init__(
        self,
        mechanisms: Mechanisms,
        llm: Optional[LLMClient] = None,
        memory: Optional[MemoryStore] = None,
        policy: Optional[AutonomyPolicy] = None,
        planner: Optional[RemediationPlanner] = None,
        shadow: bool = False,
        notifier=None,
    ) -> None:
        self.m = mechanisms
        self.memory = memory
        self.rca = RCAEngine(llm=llm, memory=memory)
        self.policy = policy or AutonomyPolicy()
        self.planner = planner or RemediationPlanner(self.policy)
        self.shadow = shadow
        self.notifier = notifier
        self.pager = None
        self._cost = CostEstimator()

    # --- THE LOOP ---------------------------------------------------------- #
    def handle(self, inc: Incident,
               seen_roots: Optional[dict] = None) -> IncidentOutcome:
        seen_roots = seen_roots if seen_roots is not None else {}
        print(f"\n=== Incident {inc.id}: {inc.summary} ===")

        ctx = self.m.read_context(inc.asset_urn)
        log("context", f"{ctx.name}: {len(ctx.upstream)} upstream, "
                       f"{len(ctx.downstream)} downstream, tags={ctx.tags}")

        rca = self.rca.analyze(inc, ctx)
        self._log_rca(rca)

        if self.notifier:
            cost = self._cost.estimate(ctx, rca.change_type.value)
            self.notifier.on_detect(inc, ctx, rca, cost)

        root_key = (rca.root_cause_asset, rca.root_cause_column)
        if root_key in seen_roots:
            log("correlate", f"same root cause as {seen_roots[root_key]} — "
                             f"skipping duplicate mitigation")
            return self._outcome(inc, rca, "correlated", resolved=False, actions=[])
        seen_roots[root_key] = inc.id

        tier = self.policy.tier(ctx, rca)
        log("policy", f"tier={tier.value} ({self.policy.explain(tier, ctx, rca)})")

        if rca.change_type in _CODE_CHANGES:
            return self._remediate_code(inc, ctx, rca)
        return self._remediate_data(inc, ctx, rca, tier)

    # --- remediation paths -------------------------------------------- #
    def _remediate_code(self, inc, ctx, rca) -> IncidentOutcome:
        """A code-level incident. When an automatic fix applies — a dependency or
        API migration — the remediation is a pull request. When it doesn't — a
        human's commit to a pipeline source — the agent cannot (and should not)
        revert it: it flags the downstream assets and pages a reviewer, and the
        incident is *contained*, not claimed as resolved."""
        pr = self.m.propose_fix(inc, ctx, rca.narrative)
        if _is_artifact(pr):
            log("fix", f"generated migration -> {pr}")
            self._resolve(inc, ctx, rca, actions_taken=["propose_fix"],
                          resolution=f"auto-migration: {pr}")
            return self._outcome(inc, rca, "code_fix", resolved=True,
                                 actions=["propose_fix"], pr=pr)

        log("fix", "no automatic fix applies — flagging downstream and paging a "
                   "human to review the change")
        actions = [ActionRecord(action_type=ActionType.TAG_ASSET, target=n.urn,
                                params={"tag": "do-not-trust"},
                                note="downstream of an unreviewed code change",
                                incident_id=inc.id)
                   for n in ctx.downstream]
        journal = self._apply(actions)
        applied = [a.action_type.value for a in journal if a.status == "applied"]
        self._escalate(inc, ctx, rca, AutonomyTier.HUMAN_ONLY,
                       reason="code change needs human review")
        self._resolve(inc, ctx, rca, actions_taken=applied,
                      resolution="contained: downstream flagged, change awaiting "
                                 "human review",
                      resolved=False)
        return self._outcome(inc, rca, "contained", resolved=False, actions=applied)

    def _remediate_data(self, inc, ctx, rca, tier: AutonomyTier) -> IncidentOutcome:
        actions, withheld = self.planner.plan(rca, ctx, tier)
        for a in withheld:
            log("withheld", f"{a.action_type.value} on {_short(a.target)} — "
                            f"blocked by tier {tier.value}")

        if not actions:
            log("plan", "no autonomous action available for this incident")
            self._escalate(inc, ctx, rca, tier, reason="nothing the agent may do")
            return self._outcome(inc, rca, "escalated", resolved=False, actions=[])

        if self.shadow:
            self._simulate(inc, actions)
            return self._outcome(inc, rca, "shadow", resolved=False,
                                 actions=[a.action_type.value for a in actions])

        actions = self._gate_approval(inc, ctx, rca, tier, actions)
        if not actions:
            log("approval", "denied — no actions will be applied")
            self._escalate(inc, ctx, rca, tier, reason="approval denied via Slack")
            return self._outcome(inc, rca, "escalated", resolved=False, actions=[])

        journal = self._apply(actions)
        applied = [a for a in journal if a.status == "applied"]
        failed = [a for a in journal if a.status == "failed"]
        if failed:
            log("act", f"{len(failed)} action(s) failed — the gate decides "
                       f"whether what did apply was enough")

        result = self.m.run_checks(inc.asset_urn)
        log("validate", f"passed={result.passed} "
                        f"({len(result.checks_run)} checks"
                        + ("" if result.passed else f", failures: {result.failures}")
                        + ")")

        applied_types = [a.action_type.value for a in applied]
        if result.passed and applied:
            self._succeed(inc, ctx, rca, tier, applied)
            return self._outcome(inc, rca, "resolved", resolved=True,
                                 actions=applied_types)
        elif result.passed and not applied:
            # Nothing we did took effect, so a green gate is not our success.
            log("validate", "gate is green but no action applied — not claiming "
                            "credit for it")
            self._escalate(inc, ctx, rca, tier, reason="all actions failed")
            return self._outcome(inc, rca, "escalated", resolved=False, actions=[])
        elif self.policy.is_containment_only(applied):
            # Nothing in the plan could have repaired this, so a red gate is the
            # expected outcome rather than a failed mitigation.
            self._contain(inc, ctx, rca, tier, applied, result.failures)
            return self._outcome(inc, rca, "contained", resolved=False,
                                 actions=applied_types)
        else:
            self._roll_back(inc, ctx, rca, tier, applied, result.failures)
            return self._outcome(inc, rca, "rolled_back", resolved=False,
                                 actions=applied_types)

    @staticmethod
    def _outcome(inc, rca, status: str, resolved: bool,
                 actions: list[str], pr=None) -> IncidentOutcome:
        return IncidentOutcome(
            incident_id=inc.id, status=status, resolved=resolved,
            change_type=rca.change_type, root_cause_asset=rca.root_cause_asset,
            root_cause_column=rca.root_cause_column, actions_taken=actions, pr=pr,
        )

    # --- outcomes ------------------------------------------------------ #
    def _simulate(self, inc: Incident, actions: list[ActionRecord]) -> None:
        """Record the plan without executing any of it.

        The incident is left open on purpose: shadow mode is an argument about
        what the agent would have done, and closing incidents it never touched
        would make that argument dishonest.
        """
        journal = getattr(self.m, "journal", None)
        for a in actions:
            a.incident_id = inc.id
            if journal is not None:
                journal.record_simulated(a, inc.id)
            log("shadow", f"would {a.action_type.value} -> {_short(a.target)}"
                          + (f"  ({a.note})" if a.note else ""))
        log("shadow", f"{len(actions)} action(s) recorded, none applied — "
                      f"incident left open")

    def _apply(self, actions: list[ActionRecord]) -> list[ActionRecord]:
        journal: list[ActionRecord] = []
        for a in actions:
            applied = self.m.act(a)
            journal.append(applied)
            if applied.status == "applied":
                log("act", f"{a.action_type.value} -> {_short(a.target)}  "
                           f"(inverse ready: {applied.inverse is not None})"
                    + (f"  {applied.note}" if applied.note else ""))
            else:
                log("act", f"{a.action_type.value} -> {_short(a.target)}  "
                           f"FAILED: {applied.note}")
        return journal

    def _gate_approval(self, inc, ctx, rca, tier, actions) -> list[ActionRecord]:
        """Ask a human before mutating data on a sensitive asset.

        Only *mutating* actions are ever gated — protective ones (tag, pause)
        run at every tier, because withholding a warning while waiting for a
        human is itself the risky choice. And gating only bites at PR_ONLY:
        AUTO is by definition the routine case, and HUMAN_ONLY has already had
        its mutating actions stripped by the planner, so there is nothing left
        to approve there. That is the "critical needs approval, routine
        reversible work does not" rule, expressed where it actually applies.

        On approval: return all actions unchanged.
        On deny: return empty list (escalate path).
        On timeout with protective_only fallback: return only protective actions.
        """
        if not self.policy.needs_human(tier):
            return actions
        if not self.notifier or not hasattr(self.notifier, "request_approval"):
            return actions

        mutating = [a for a in actions if not self.policy.is_protective(a.action_type)]
        if not mutating:
            return actions

        decision = self.notifier.request_approval(inc, mutating, ctx, rca)

        if decision.approved:
            log("approval", f"approved by {decision.decided_by}")
            return actions

        if decision.timed_out:
            protective = [a for a in actions if self.policy.is_protective(a.action_type)]
            if protective:
                log("approval", f"timed out — proceeding with {len(protective)} "
                                f"protective action(s) only")
                return protective
            return []

        return []

    def _succeed(self, inc, ctx, rca, tier, applied) -> None:
        released, failed = self.m.release_containment(inc.id)
        if released:
            log("restore", f"lifted {released} protective measure(s) — breaker "
                           f"closed, downstream flags cleared"
                + (f" ({failed} could not be lifted)" if failed else ""))

        pr = self._propose_fix(inc, ctx, rca) if self.policy.needs_human(tier) else None
        applied_types = [a.action_type.value for a in applied]
        self._resolve(
            inc, ctx, rca,
            actions_taken=applied_types,
            resolution=(f"mitigated ({rca.recommended_mitigation})"
                        + (f"; fix for review: {pr}" if pr else "")),
        )

        if self.notifier:
            cost = self._cost.estimate(ctx, rca.change_type.value)
            outcome = self._outcome(inc, rca, "resolved", True, applied_types, pr)
            self.notifier.on_resolve(inc, ctx, rca, cost, outcome)
        if self.pager:
            self.pager.resolve(inc.id)

    def _propose_fix(self, inc, ctx, rca) -> Optional[str]:
        """Ask for a code fix, and only report one if it actually produced an
        artifact. A mitigation that says "fix: nothing to fix" reads as though a
        fix exists, which is worse than saying nothing."""
        result = self.m.propose_fix(inc, ctx, rca.narrative)
        if not result or not _is_artifact(result):
            log("fix", "no code change applies here — the mitigation is the "
                       "remediation; owners still need to make it permanent")
            return None
        log("fix", f"permanent fix for review: {result}")
        return result

    def _contain(self, inc, ctx, rca, tier, applied, failures) -> None:
        held = ", ".join(sorted({a.action_type.value for a in applied}))
        log("contain", f"no repair exists for {rca.change_type.value} — "
                       f"holding {len(applied)} protective action(s): {held}")
        log("contain", f"still failing (expected): {failures}")
        self._escalate(inc, ctx, rca, tier,
                       reason="contained, but only a human can resolve this")
        applied_types = [a.action_type.value for a in applied]
        self._resolve(
            inc, ctx, rca,
            actions_taken=applied_types,
            resolution=(f"CONTAINED, awaiting human — {rca.recommended_mitigation}. "
                        f"Protection held: {held}. Outstanding: {failures}"),
            resolved=False,
        )

        if self.notifier:
            cost = self._cost.estimate(ctx, rca.change_type.value)
            outcome = self._outcome(inc, rca, "contained", False, applied_types)
            self.notifier.on_contain(inc, ctx, rca, cost, outcome, failures)

    def _roll_back(self, inc, ctx, rca, tier, applied, failures) -> None:
        reverted, failed = self.m.rollback(inc.id, mutating_only=True)
        held = [a for a in applied if self.policy.is_protective(a.action_type)]
        log("rollback", f"validation failed — withdrew {reverted} data action(s)"
                        + (f", {failed} could not be reverted" if failed else ""))
        if held:
            log("rollback", f"keeping {len(held)} protective action(s) in place — "
                            f"the pipeline is still bad, so the warning stands")
        self._escalate(inc, ctx, rca, tier,
                       reason=f"validation still failing: {failures}")

        if self.notifier:
            applied_types = [a.action_type.value for a in applied]
            outcome = self._outcome(inc, rca, "rolled_back", False, applied_types)
            self.notifier.on_rollback(inc, ctx, rca, outcome, failures)

    def _escalate(self, inc, ctx, rca, tier, reason: str) -> None:
        log("escalate", f"paging {ctx.owners or ['(no owner on the asset)']} — {reason}")
        if self.policy.needs_human(tier):
            self._propose_fix(inc, ctx, rca)
        if self.notifier:
            self.notifier.on_escalate(inc, ctx, rca, tier, reason)
        if self.pager:
            self.pager.trigger(inc, ctx, rca, tier, reason)
        else:
            log("escalate", "no pager configured (set PAGERDUTY_ROUTING_KEY)")

    def _resolve(self, inc, ctx, rca, actions_taken: list[str],
                 resolution: str, resolved: bool = True) -> None:
        cost = CostEstimator().estimate(ctx, rca.change_type.value)
        verb = "avoided" if resolved else "at risk (unresolved)"
        log("cost", f"est. exposure {verb}: ${cost.dollars:,.0f} — {cost.basis}")

        pm = PostMortem(
            incident_id=inc.id,
            asset_urn=inc.asset_urn,
            root_cause=f"[{rca.change_type.value}] {rca.narrative}",
            blast_radius=[n.urn for n in ctx.downstream],
            actions_taken=actions_taken,
            resolution=resolution,
            resolved_at=datetime.now(timezone.utc),
            estimated_impact_usd=cost.dollars,
            impact_basis=cost.basis,
        )
        self.m.write_back(pm, resolved=resolved)
        if resolved:
            log("resolve", "incident resolved; post-mortem written to the graph "
                           "(asset + model card), degraded tags cleared")
        else:
            log("resolve", "incident CONTAINED, not resolved; post-mortem written "
                           "to the graph, degraded tags left in place")

    # --- reporting ----------------------------------------------------- #
    @staticmethod
    def _log_rca(rca: RootCauseAnalysis) -> None:
        log("rca", f"[{rca.change_type.value}] {rca.narrative}")
        log("rca", f"root cause: {_short(rca.root_cause_asset)}"
                   f".{rca.root_cause_column}  (confidence {rca.confidence})")
        if rca.precedents:
            log("memory", f"cited {len(rca.precedents)} prior incident(s): "
                          f"{rca.precedents}")
        log("blast", f"{len(rca.blast_radius)} affected: {rca.blast_radius}")

    def run(self) -> list[IncidentOutcome]:
        incidents = self.m.detect_incidents()
        log("detect", f"{len(incidents)} open incident(s)")
        seen_roots: dict = {}  # shared across incidents to correlate root causes
        outcomes = [self.handle(inc, seen_roots) for inc in incidents]
        if outcomes:
            resolved = sum(1 for o in outcomes if o.resolved)
            print(f"\n=== loop complete — {resolved}/{len(outcomes)} resolved, "
                  f"{len(outcomes) - resolved} contained/escalated ===")
        else:
            print("\n=== loop complete ===")
        return outcomes


def _short(urn: str) -> str:
    """A readable tail for log lines."""
    return short_name(urn) or urn


def _is_artifact(result: str) -> bool:
    """CodeFixTool reports its failures as prose in the same return value it uses
    for a diff path or PR URL, so a real artifact has to be recognised."""
    lowered = result.lower()
    if lowered.startswith(("http://", "https://")):
        return True
    return not any(phrase in lowered for phrase in
                   ("no affected files", "could not generate", "nothing to fix"))


if __name__ == "__main__":
    from agent.tools.mechanisms.fakes import FakeMechanisms

    SentinelAgent(FakeMechanisms()).run()
