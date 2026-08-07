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
    AutonomyTier,
    ChangeType,
    ContextBundle,
    Incident,
    Mechanisms,
    MemoryStore,
    RootCauseAnalysis,
)
from agent.llm import LLMClient
from agent.planner import RemediationPlanner
from agent.policy import AutonomyPolicy
from agent.rca import RCAEngine

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
    ) -> None:
        self.m = mechanisms
        self.memory = memory
        self.rca = RCAEngine(llm=llm, memory=memory)
        self.policy = policy or AutonomyPolicy()
        self.planner = planner or RemediationPlanner(self.policy)
        # Shadow mode: reason all the way to a plan, record it, change nothing.
        # This is how a team decides whether to trust the agent before granting
        # it the ability to act.
        self.shadow = shadow

    # --- THE LOOP ---------------------------------------------------------- #
    def handle(self, inc: Incident, seen_roots: Optional[dict] = None) -> None:
        seen_roots = seen_roots if seen_roots is not None else {}
        print(f"\n=== Incident {inc.id}: {inc.summary} ===")

        ctx = self.m.read_context(inc.asset_urn)
        log("context", f"{ctx.name}: {len(ctx.upstream)} upstream, "
                       f"{len(ctx.downstream)} downstream, tags={ctx.tags}")

        rca = self.rca.analyze(inc, ctx)
        self._log_rca(rca)

        # One upstream change can trip many downstream assertions. Mitigate the
        # shared root cause once; note the rest rather than acting again.
        root_key = (rca.root_cause_asset, rca.root_cause_column)
        if root_key in seen_roots:
            log("correlate", f"same root cause as {seen_roots[root_key]} — "
                             f"skipping duplicate mitigation")
            return
        seen_roots[root_key] = inc.id

        tier = self.policy.tier(ctx, rca)
        log("policy", f"tier={tier.value} ({self.policy.explain(tier, ctx, rca)})")

        if rca.change_type in _CODE_CHANGES:
            self._remediate_code(inc, ctx, rca)
            return

        self._remediate_data(inc, ctx, rca, tier)

    # --- remediation paths -------------------------------------------- #
    def _remediate_code(self, inc, ctx, rca) -> None:
        """A dependency or API break is fixed by changing code, so the
        remediation is a pull request rather than a data action."""
        pr = self.m.propose_fix(inc, ctx, rca.narrative)
        log("fix", f"generated migration -> {pr}")
        self._resolve(inc, ctx, rca, actions_taken=["propose_fix"],
                      resolution=f"auto-migration: {pr}")

    def _remediate_data(self, inc, ctx, rca, tier: AutonomyTier) -> None:
        actions, withheld = self.planner.plan(rca, ctx, tier)
        for a in withheld:
            log("withheld", f"{a.action_type.value} on {_short(a.target)} — "
                            f"blocked by tier {tier.value}")

        if not actions:
            log("plan", "no autonomous action available for this incident")
            self._escalate(inc, ctx, rca, tier, reason="nothing the agent may do")
            return

        if self.shadow:
            self._simulate(inc, actions)
            return

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

        if result.passed and applied:
            self._succeed(inc, ctx, rca, tier, applied)
        elif result.passed and not applied:
            # Nothing we did took effect, so a green gate is not our success.
            log("validate", "gate is green but no action applied — not claiming "
                            "credit for it")
            self._escalate(inc, ctx, rca, tier, reason="all actions failed")
        elif self.policy.is_containment_only(applied):
            # Nothing in the plan could have repaired this, so a red gate is the
            # expected outcome rather than a failed mitigation.
            self._contain(inc, ctx, rca, tier, applied, result.failures)
        else:
            self._roll_back(inc, ctx, rca, tier, applied, result.failures)

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

    def _succeed(self, inc, ctx, rca, tier, applied) -> None:
        # The pipeline is healthy again, so the warnings have to come down with
        # it: a breaker left open after the fix keeps the scoring job down for no
        # reason, and flags that outlive their incident stop being read.
        released, failed = self._release_containment(inc.id)
        if released:
            log("restore", f"lifted {released} protective measure(s) — breaker "
                           f"closed, downstream flags cleared"
                + (f" ({failed} could not be lifted)" if failed else ""))

        pr = self._propose_fix(inc, ctx, rca) if self.policy.needs_human(tier) else None
        self._resolve(
            inc, ctx, rca,
            actions_taken=[a.action_type.value for a in applied],
            resolution=(f"mitigated ({rca.recommended_mitigation})"
                        + (f"; fix for review: {pr}" if pr else "")),
        )

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
        """The agent did everything available to it and the incident persists.

        Some things genuinely cannot be repaired from here — a feed that stopped
        delivering has no rows to restore. Withdrawing the protection because the
        pipeline is still broken would be exactly backwards, so the tags and
        breakers stay up and a human is paged. The post-mortem is still recorded:
        memory should learn from the incidents we cannot fix too.
        """
        held = ", ".join(sorted({a.action_type.value for a in applied}))
        log("contain", f"no repair exists for {rca.change_type.value} — "
                       f"holding {len(applied)} protective action(s): {held}")
        log("contain", f"still failing (expected): {failures}")
        self._escalate(inc, ctx, rca, tier,
                       reason="contained, but only a human can resolve this")
        self._resolve(
            inc, ctx, rca,
            actions_taken=[a.action_type.value for a in applied],
            resolution=(f"CONTAINED, awaiting human — {rca.recommended_mitigation}. "
                        f"Protection held: {held}. Outstanding: {failures}"),
            resolved=False,
        )

    def _roll_back(self, inc, ctx, rca, tier, applied, failures) -> None:
        reverted, failed = self._rollback(inc.id, mutating_only=True)
        held = [a for a in applied if self.policy.is_protective(a.action_type)]
        log("rollback", f"validation failed — withdrew {reverted} data action(s)"
                        + (f", {failed} could not be reverted" if failed else ""))
        if held:
            log("rollback", f"keeping {len(held)} protective action(s) in place — "
                            f"the pipeline is still bad, so the warning stands")
        self._escalate(inc, ctx, rca, tier,
                       reason=f"validation still failing: {failures}")

    def _release_containment(self, incident_id: str) -> tuple[int, int]:
        release = getattr(self.m, "release_containment", None)
        if release is None:
            return 0, 0
        try:
            return release(incident_id)
        except Exception:
            return 0, 0

    def _rollback(self, incident_id: str,
                  mutating_only: bool = False) -> tuple[int, int]:
        rollback = getattr(self.m, "rollback", None)
        if rollback is None:
            return 0, 0
        try:
            return rollback(incident_id, mutating_only=mutating_only)
        except TypeError:
            # a Mechanisms implementation with the older single-argument rollback
            return rollback(incident_id)

    def _escalate(self, inc, ctx, rca, tier, reason: str) -> None:
        log("escalate", f"paging {ctx.owners or ['(no owner on the asset)']} — {reason}")
        if self.policy.needs_human(tier):
            self._propose_fix(inc, ctx, rca)

    def _resolve(self, inc, ctx, rca, actions_taken: list[str],
                 resolution: str, resolved: bool = True) -> None:
        from agent.contracts import PostMortem

        pm = PostMortem(
            incident_id=inc.id,
            asset_urn=inc.asset_urn,
            root_cause=f"[{rca.change_type.value}] {rca.narrative}",
            blast_radius=[n.urn for n in ctx.downstream],
            actions_taken=actions_taken,
            resolution=resolution,
            resolved_at=datetime.now(timezone.utc),
        )
        self._write_back(pm, resolved)
        if resolved:
            log("resolve", "incident resolved; post-mortem written to the graph "
                           "(asset + model card), degraded tags cleared")
        else:
            log("resolve", "incident CONTAINED, not resolved; post-mortem written "
                           "to the graph, degraded tags left in place")

    def _write_back(self, pm, resolved: bool) -> None:
        try:
            self.m.write_back(pm, resolved=resolved)
        except TypeError:
            # a Mechanisms implementation predating the contained/resolved split
            self.m.write_back(pm)

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

    def run(self) -> None:
        incidents = self.m.detect_incidents()
        log("detect", f"{len(incidents)} open incident(s)")
        seen_roots: dict = {}  # shared across incidents to correlate root causes
        for inc in incidents:
            self.handle(inc, seen_roots)
        print("\n=== loop complete ===")


def _short(urn: str) -> str:
    """A readable tail for log lines."""
    from agent.tools.graph.urns import short_name

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
