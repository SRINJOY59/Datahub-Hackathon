"""Sentinel orchestrator — the closed remediation loop (walking skeleton).

    detect -> context -> root-cause -> policy tier -> plan -> act (journaled)
           -> validate -> (pass) resolve + write post-mortem
                       -> (fail) rollback via journal + escalate

This is the POLICY plane. RCA / policy / planning are intentionally thin stubs
for the partner to flesh out; the value proven here is that the loop runs, the
action journal records inverses, and validation drives keep-or-rollback. It runs
against any `Mechanisms` implementation — fakes today, the real thing later.

Run:  python agent/orchestrator.py
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
    Incident,
    Mechanisms,
    MemoryStore,
    PostMortem,
)
from agent.llm import LLMClient
from agent.rca import RCAEngine


def log(stage: str, msg: str) -> None:
    print(f"  [{stage:9s}] {msg}")


class SentinelAgent:
    def __init__(
        self,
        mechanisms: Mechanisms,
        llm: Optional[LLMClient] = None,
        memory: Optional[MemoryStore] = None,
    ) -> None:
        self.m = mechanisms
        self.memory = memory
        self.rca = RCAEngine(llm=llm, memory=memory)

    # --- POLICY-PLANE STUBS (partner fleshes these out) -------------------- #
    def _autonomy_tier(self, ctx: ContextBundle) -> AutonomyTier:
        if "PII" in ctx.tags:
            return AutonomyTier.HUMAN_ONLY
        if "Tier-Critical" in ctx.tags:
            return AutonomyTier.PR_ONLY
        return AutonomyTier.AUTO

    def _plan(self, ctx: ContextBundle) -> list[ActionRecord]:
        # stub: mitigate by pinning the feature and rerouting the model, and tag
        # downstream do-not-trust. Real planner reasons over blast radius.
        actions = [
            ActionRecord(ActionType.PIN_FEATURE, ctx.asset_urn,
                         note="pin feature to last-known-good snapshot"),
            ActionRecord(ActionType.REPOINT_MODEL,
                         "fraud_scoring_api",
                         params={"to": "last_good_version"},
                         note="reroute scoring to last-good model version"),
        ]
        for node in ctx.downstream:
            actions.append(ActionRecord(ActionType.TAG_ASSET, node.urn,
                                        params={"tag": "do-not-trust"}))
        return actions

    # --- THE LOOP ---------------------------------------------------------- #
    def handle(self, inc: Incident, seen_roots: Optional[dict] = None) -> None:
        seen_roots = seen_roots if seen_roots is not None else {}
        print(f"\n=== Incident {inc.id}: {inc.summary} ===")

        ctx = self.m.read_context(inc.asset_urn)
        log("context", f"{ctx.name}: {len(ctx.upstream)} upstream, "
                       f"{len(ctx.downstream)} downstream, tags={ctx.tags}")

        rca = self.rca.analyze(inc, ctx)
        log("rca", f"[{rca.change_type.value}] {rca.narrative}")
        log("rca", f"root cause: {rca.root_cause_asset.split(',')[-2] if ',' in rca.root_cause_asset else rca.root_cause_asset}"
                   f".{rca.root_cause_column}  (confidence {rca.confidence})")
        if rca.precedents:
            log("memory", f"cited {len(rca.precedents)} prior incident(s): {rca.precedents}")
        log("blast", f"{len(rca.blast_radius)} affected: {rca.blast_radius}")

        # Correlated incidents: one upstream change can trip many downstream
        # assertions. Mitigate the shared root cause once; note the rest.
        root_key = (rca.root_cause_asset, rca.root_cause_column)
        if root_key in seen_roots:
            log("correlate", f"same root cause as {seen_roots[root_key]} — "
                             f"skipping duplicate mitigation")
            return
        seen_roots[root_key] = inc.id

        tier = self._autonomy_tier(ctx)
        log("policy", f"autonomy tier = {tier.value}")

        # Code / dependency incidents: remediation is a fix PR (apply the change),
        # not a data rollback.
        if rca.change_type in (ChangeType.DEPENDENCY_CHANGE, ChangeType.CODE_CHANGE):
            pr = self.m.propose_fix(inc, ctx, rca.narrative)
            log("fix", f"generated migration -> {pr}")
            self._resolve(inc, ctx, rca, actions_taken=["propose_fix"],
                          resolution=f"auto-migration: {pr}")
            return

        actions = self._plan(ctx)
        journal: list[ActionRecord] = []
        for a in actions:
            applied = self.m.act(a)
            journal.append(applied)
            log("act", f"{a.action_type.value} -> {a.target.split(',')[-1][:40]}  "
                       f"(inverse ready: {applied.inverse is not None})")

        result = self.m.run_checks(inc.asset_urn)
        log("validate", f"passed={result.passed} "
                        f"({'clean' if result.passed else result.failures})")

        if result.passed:
            pr = None
            if tier in (AutonomyTier.PR_ONLY, AutonomyTier.HUMAN_ONLY):
                pr = self.m.propose_fix(inc, ctx, rca.narrative)
                log("fix", f"draft PR opened: {pr}")
            self._resolve(
                inc, ctx, rca,
                actions_taken=[a.action_type.value for a in journal],
                resolution=(f"mitigated ({rca.recommended_mitigation}); "
                            + (f"fix PR {pr}" if pr else "auto-fixed")),
            )
        else:
            for a in reversed(journal):
                self.m.undo(a)
            log("rollback", f"validation failed — reverted {len(journal)} actions")
            log("escalate", f"paged owners {ctx.owners} with full RCA")

    def _resolve(self, inc, ctx, rca, actions_taken: list[str], resolution: str) -> None:
        pm = PostMortem(
            incident_id=inc.id,
            asset_urn=inc.asset_urn,
            root_cause=f"[{rca.change_type.value}] {rca.narrative}",
            blast_radius=[n.urn for n in ctx.downstream],
            actions_taken=actions_taken,
            resolution=resolution,
            resolved_at=datetime.now(timezone.utc),
        )
        self.m.write_back(pm)
        if self.memory:
            self.memory.record(pm)
            log("memory", "post-mortem recorded to DataHub for future recall")
        log("resolve", "incident resolved; post-mortem written to graph")

    def run(self) -> None:
        incidents = self.m.detect_incidents()
        log("detect", f"{len(incidents)} open incident(s)")
        seen_roots: dict = {}  # shared across incidents to correlate root causes
        for inc in incidents:
            self.handle(inc, seen_roots)
        print("\n=== loop complete ===")


if __name__ == "__main__":
    from agent.tools.mechanisms.fakes import FakeMechanisms

    SentinelAgent(FakeMechanisms()).run()
