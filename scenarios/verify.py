"""End-to-end verification: run every scenario through the real agent and check
what it did against the scenario's declared Expectation.

    python -m scenarios verify            # every scenario
    python -m scenarios verify unit_bug   # one

Each scenario is an executable test case. For each one the harness:

  1. resets to a clean, snapshotted baseline (so the agent has a last-good to
     roll back to),
  2. injects the failure,
  3. checks dbt's own verdict against `trips_dbt_tests` — proving the silent
     scenarios really are silent (every assertion green) rather than quietly
     relying on one,
  4. runs the agent and captures the IncidentOutcome,
  5. asserts the agent classified the right change, blamed the right asset, took
     the declared actions, and reached the right outcome (resolved for fixable
     incidents, contained for the ones nothing can repair),
  6. resets again so the next scenario starts clean.

Memory is left out on purpose: a scenario is a statement about how the agent
reasons on this incident from the evidence in front of it, not about what it
remembers from the last run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agent.journal import ActionJournal
from agent.llm import LLMClient
from agent.orchestrator import SentinelAgent
from agent.tools.mechanisms.composite import RealMechanisms
from scenarios import registry
from scenarios.base import SENTINEL_DIR, BaseScenario, PipelineReset, run_dbt

_VERIFY_JOURNAL = SENTINEL_DIR / "verify_journal.jsonl"


@dataclass
class CheckResult:
    scenario: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    detail: str = ""


def _matching_incident(incidents, expected_signal):
    if expected_signal:
        for inc in incidents:
            if inc.signal_type.value == expected_signal:
                return inc
    return incidents[0] if incidents else None


def _fresh_agent(llm: LLMClient) -> SentinelAgent:
    # a per-scenario journal so one scenario's actions can't be mistaken for
    # another's during rollback; memory off for deterministic, isolated checks.
    if _VERIFY_JOURNAL.exists():
        _VERIFY_JOURNAL.unlink()
    mechanisms = RealMechanisms(llm=llm, memory=None,
                                journal=ActionJournal(_VERIFY_JOURNAL))
    return SentinelAgent(mechanisms, llm=llm, memory=None)


def verify_one(cls: type[BaseScenario], llm: LLMClient) -> CheckResult:
    exp = cls.expectation
    failures: list[str] = []

    # 1-2. clean baseline, then inject
    PipelineReset().run()
    cls().apply(reingest_after=True)

    # 3. dbt's own verdict must match the scenario's silent/loud claim
    dbt_green = run_dbt(["test"])
    if dbt_green == exp.trips_dbt_tests:
        failures.append(
            f"dbt green={dbt_green} contradicts trips_dbt_tests={exp.trips_dbt_tests}")

    # 4. run the agent on the matching incident
    agent = _fresh_agent(llm)
    incidents = agent.m.detect_incidents()
    if exp.signal_type and not any(
            i.signal_type.value == exp.signal_type for i in incidents):
        got = [i.signal_type.value for i in incidents] or "nothing"
        return CheckResult(cls.name, False,
                           [f"no detector emitted '{exp.signal_type}' (got {got})"])

    inc = _matching_incident(incidents, exp.signal_type)
    if inc is None:
        return CheckResult(cls.name, False, ["no incident detected"])

    outcome = agent.handle(inc)
    detail = (f"status={outcome.status} change={outcome.change_type.value} "
              f"actions={outcome.actions_taken}")

    # 5. assert the outcome against the expectation
    if exp.change_type and outcome.change_type.value != exp.change_type:
        failures.append(f"change_type: got '{outcome.change_type.value}', "
                        f"expected '{exp.change_type}'")
    if exp.root_table and exp.root_table not in outcome.root_cause_asset:
        failures.append(f"root_table '{exp.root_table}' not in blamed asset "
                        f"'{outcome.root_cause_asset}'")
    if exp.root_column and outcome.root_cause_column != exp.root_column:
        failures.append(f"root_column: got '{outcome.root_cause_column}', "
                        f"expected '{exp.root_column}'")
    for a in exp.actions:
        if a not in outcome.actions_taken:
            failures.append(f"action '{a}' not taken (took {outcome.actions_taken})")
    if exp.checks_pass_after_act and not outcome.resolved:
        failures.append(f"expected resolution, got '{outcome.status}'")
    if not exp.checks_pass_after_act and outcome.resolved:
        failures.append("expected containment, but the agent claimed resolution")

    return CheckResult(cls.name, not failures, failures, detail)


def main(names: list[str] | None = None) -> int:
    to_run = ([registry.get(n) for n in names] if names
              else registry.all_scenarios())
    if any(c is None for c in to_run):
        missing = [n for n, c in zip(names or [], to_run) if c is None]
        raise SystemExit(f"unknown scenario(s): {', '.join(missing)}")

    llm = LLMClient()
    print(f"LLM: {llm.model if llm.available() else 'not configured (RCA fallback)'}")

    results: list[CheckResult] = []
    for cls in to_run:
        print(f"\n{'#' * 70}\n# VERIFY: {cls.name} — {cls.description}\n{'#' * 70}")
        try:
            results.append(verify_one(cls, llm))
        except Exception as e:
            results.append(CheckResult(cls.name, False,
                                       [f"harness error: {type(e).__name__}: {e}"]))
        finally:
            PipelineReset().run()  # leave a clean world for the next one

    return _report(results)


def _report(results: list[CheckResult]) -> int:
    print(f"\n{'=' * 70}\nVERIFICATION SUMMARY\n{'=' * 70}")
    passed = 0
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] {r.scenario:24s} {r.detail}")
        for f in r.failures:
            print(f"         - {f}")
        passed += r.passed
    print(f"\n{passed}/{len(results)} scenarios verified.")
    return 0 if passed == len(results) else 1
