"""Checking that the agent does what each scenario says it should.

Every scenario declares an `Expectation` — the signal it ought to raise, the
change type the RCA ought to land on, the actions the planner ought to choose,
and whether the pipeline can actually be repaired afterwards. This runs the real
three-step loop against each of them and compares.

The point is that the claims in the README are re-checkable rather than
anecdotal. A scenario whose expectation no longer matches reality shows up as a
failed row, which is either a regression to fix or an expectation that was
written optimistically and needs correcting — and both are worth knowing.

    python -m scenarios verify <name>     one scenario
    python -m scenarios verify --all      the whole matrix
    python -m scenarios verify --all --plan-only
                                          detection, RCA and planning only:
                                          no mitigation, nothing mutated, fast

Full mode mutates the warehouse and the model registry, and resets between
scenarios, so it takes a while. `--plan-only` covers the reasoning half in a
fraction of the time and is the one to run habitually.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from scenarios import registry
from scenarios.base import BaseScenario, Expectation, PipelineReset, reingest

PASS, FAIL, SKIP = "PASS", "FAIL", "skip"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status != FAIL


@dataclass
class Report:
    scenario: str
    checks: list[Check] = field(default_factory=list)
    error: str = ""

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, PASS if ok else FAIL, detail))

    def skip(self, name: str, why: str) -> None:
        self.checks.append(Check(name, SKIP, why))

    @property
    def passed(self) -> bool:
        return not self.error and all(c.ok for c in self.checks)

    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]


class ScenarioVerifier:
    """Runs one scenario and grades it against its own expectation."""

    def __init__(self, plan_only: bool = False, reingest_after: bool = True) -> None:
        self.plan_only = plan_only
        self.reingest_after = reingest_after

    # ------------------------------------------------------------------ #
    def verify(self, cls: type[BaseScenario]) -> Report:
        report = Report(scenario=cls.name)
        expectation = cls.expectation
        try:
            self._run(cls, expectation, report)
        except Exception as e:  # a broken scenario is a failed row, not a crash
            report.error = f"{type(e).__name__}: {e}"
        return report

    # ------------------------------------------------------------------ #
    def _run(self, cls: type[BaseScenario], exp: Expectation,
             report: Report) -> None:
        from agent.llm import LLMClient
        from agent.rca import RCAEngine
        from agent.tools.mechanisms.composite import RealMechanisms
        from agent.tools.warehouse.dbt_runner import DbtRunner
        from memory.base import get_memory

        print(f"\n--- {cls.name}: injecting ---")
        cls().apply(reingest_after=self.reingest_after)

        # 1. does dbt see it? For half the scenarios the answer is deliberately no.
        dbt_ok = DbtRunner().test().ok
        report.add("dbt_visibility", dbt_ok == (not exp.trips_dbt_tests),
                   f"assertions green={dbt_ok}, expected green={not exp.trips_dbt_tests}")

        llm = LLMClient()
        memory = get_memory()
        mechanisms = RealMechanisms(llm=llm, memory=memory)

        # 2. does a detector raise the signal the scenario says it should?
        incidents = mechanisms.detect_incidents()
        match = next((i for i in incidents
                      if exp.signal_type is None
                      or i.signal_type.value == exp.signal_type), None)
        report.add("detected", match is not None,
                   f"expected {exp.signal_type}, got "
                   f"{[i.signal_type.value for i in incidents] or 'nothing'}")
        if match is None:
            return

        # 3. does the RCA land where it should?
        context = mechanisms.read_context(match.asset_urn)
        rca = RCAEngine(llm=llm, memory=memory).analyze(match, context)

        if exp.change_type:
            report.add("change_type", rca.change_type.value == exp.change_type,
                       f"expected {exp.change_type}, got {rca.change_type.value}")
        if exp.root_table:
            from agent.tools.graph.urns import table_of

            actual = table_of(rca.root_cause_asset)
            report.add("root_table", actual == exp.root_table,
                       f"expected {exp.root_table}, got {actual or '(none)'}")
        if exp.root_column:
            report.add("root_column", rca.root_cause_column == exp.root_column,
                       f"expected {exp.root_column}, got {rca.root_cause_column}")

        # 4. does the planner choose the actions the scenario says it should?
        from agent.planner import RemediationPlanner
        from agent.policy import AutonomyPolicy

        policy = AutonomyPolicy()
        tier = policy.tier(context, rca)
        actions, _ = RemediationPlanner(policy).plan(rca, context, tier)
        planned = _distinct(a.action_type.value for a in actions)
        report.add("planned_actions", planned == list(exp.actions),
                   f"expected {list(exp.actions)}, got {planned} (tier={tier.value})")

        if self.plan_only:
            report.skip("remediation", "plan-only mode")
            return

        # 5. does running it leave the pipeline where the scenario says it will?
        from agent.orchestrator import SentinelAgent

        SentinelAgent(mechanisms, llm=llm, memory=memory).handle(match)
        result = mechanisms.run_checks(match.asset_urn)
        report.add("gate_after_act", result.passed == exp.checks_pass_after_act,
                   f"expected passed={exp.checks_pass_after_act}, "
                   f"got {result.passed} {result.failures[:1]}")


def _distinct(values) -> list[str]:
    """Action types in order, collapsing repeats.

    A plan tags every downstream asset, so `tag_asset` legitimately appears many
    times. What a scenario declares is the shape of the response, not how many
    consumers happened to be attached.
    """
    out: list[str] = []
    for v in values:
        if not out or out[-1] != v:
            out.append(v)
    return out


# --------------------------------------------------------------------------- #
def render(reports: list[Report]) -> str:
    width = max((len(r.scenario) for r in reports), default=10)
    lines = ["", "=" * (width + 46), "  SCENARIO VERIFICATION", "=" * (width + 46)]
    for r in reports:
        verdict = "PASS" if r.passed else "FAIL"
        lines.append(f"  {verdict:4s}  {r.scenario:{width}s}  "
                     + " ".join(f"{c.name}={c.status}" for c in r.checks))
        if r.error:
            lines.append(f"        └─ errored: {r.error}")
        for c in r.failures():
            lines.append(f"        └─ {c.name}: {c.detail}")

    passed = sum(1 for r in reports if r.passed)
    lines += ["=" * (width + 46),
              f"  {passed}/{len(reports)} scenarios match their declared expectation",
              "=" * (width + 46), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scenarios verify")
    ap.add_argument("names", nargs="*", help="scenario names (default: --all)")
    ap.add_argument("--all", action="store_true", help="verify every scenario")
    ap.add_argument("--plan-only", action="store_true",
                    help="detection, RCA and planning only — mutate nothing")
    ap.add_argument("--no-reingest", action="store_true",
                    help="skip the DataHub refresh (detection may go stale)")
    args = ap.parse_args(argv)

    if args.all or not args.names:
        targets = registry.all_scenarios()
    else:
        targets = [registry.get(n) for n in args.names]
        if any(t is None for t in targets):
            unknown = [n for n in args.names if registry.get(n) is None]
            raise SystemExit(f"unknown scenario(s): {', '.join(unknown)}")

    verifier = ScenarioVerifier(plan_only=args.plan_only,
                                reingest_after=not args.no_reingest)
    reset = PipelineReset()

    reports: list[Report] = []
    for cls in targets:
        print(f"\n{'=' * 70}\n  resetting before {cls.name}\n{'=' * 70}")
        reset.run(reingest_after=False)
        if not args.no_reingest:
            reingest()
        reports.append(verifier.verify(cls))

    print(f"\n{'=' * 70}\n  final reset\n{'=' * 70}")
    reset.run(reingest_after=not args.no_reingest)

    print(render(reports))
    return 0 if all(r.passed for r in reports) else 1
