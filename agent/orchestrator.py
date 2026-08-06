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
    ContextBundle,
    Incident,
    Mechanisms,
    PostMortem,
)
from agent.llm import LLMClient
from agent.prompts.rca import RCA_PROMPT


def log(stage: str, msg: str) -> None:
    print(f"  [{stage:9s}] {msg}")


class SentinelAgent:
    def __init__(self, mechanisms: Mechanisms, llm: Optional[LLMClient] = None) -> None:
        self.m = mechanisms
        self.llm = llm

    # --- POLICY-PLANE STUBS (partner fleshes these out) -------------------- #
    def _root_cause(self, ctx: ContextBundle, inc: Incident) -> str:
        # Use the LLM over real lineage context when available; otherwise a
        # deterministic fallback (blame the furthest-upstream ancestor).
        if self.llm and self.llm.available():
            prompt = RCA_PROMPT.format(
                incident=inc.summary,
                context=self._context_for_prompt(ctx),
            )
            try:
                return self.llm.complete(prompt).replace("\n", " ").strip()
            except Exception as e:  # never let a flaky LLM call break the loop
                log("rca", f"(LLM call failed: {e}; using fallback)")
        origin = ctx.upstream[-1].name if ctx.upstream else ctx.name
        return f"upstream change in {origin} corrupted {ctx.name}"

    @staticmethod
    def _context_for_prompt(ctx: ContextBundle) -> str:
        return (
            f"asset: {ctx.name} ({ctx.entity_type})\n"
            f"schema: {', '.join(ctx.schema_fields)}\n"
            f"tags: {ctx.tags}\n"
            f"upstream: {[n.name for n in ctx.upstream]}\n"
            f"downstream: {[n.name for n in ctx.downstream]}\n"
            f"failed_assertions: {ctx.failed_assertions}"
        )

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
    def handle(self, inc: Incident) -> None:
        print(f"\n=== Incident {inc.id}: {inc.summary} ===")

        ctx = self.m.read_context(inc.asset_urn)
        log("context", f"{ctx.name}: {len(ctx.upstream)} upstream, "
                       f"{len(ctx.downstream)} downstream, tags={ctx.tags}")

        root_cause = self._root_cause(ctx, inc)
        log("rca", root_cause)

        blast = [n.name for n in ctx.downstream]
        log("blast", f"{len(blast)} affected: {blast}")

        tier = self._autonomy_tier(ctx)
        log("policy", f"autonomy tier = {tier.value}")

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
                pr = self.m.propose_fix(ctx, root_cause)
                log("fix", f"draft PR opened: {pr}")
            pm = PostMortem(
                incident_id=inc.id,
                asset_urn=inc.asset_urn,
                root_cause=root_cause,
                blast_radius=[n.urn for n in ctx.downstream],
                actions_taken=[a.action_type.value for a in journal],
                resolution="mitigated via rollback; " + (f"fix PR {pr}" if pr else "auto-fixed"),
                resolved_at=datetime.now(timezone.utc),
            )
            self.m.write_back(pm)
            log("resolve", "incident resolved; post-mortem written to graph")
        else:
            for a in reversed(journal):
                self.m.undo(a)
            log("rollback", f"validation failed — reverted {len(journal)} actions")
            log("escalate", f"paged owners {ctx.owners} with full RCA")

    def run(self) -> None:
        incidents = self.m.detect_incidents()
        log("detect", f"{len(incidents)} open incident(s)")
        for inc in incidents:
            self.handle(inc)
        print("\n=== loop complete ===")


if __name__ == "__main__":
    from agent.tools.fakes import FakeMechanisms

    SentinelAgent(FakeMechanisms()).run()
