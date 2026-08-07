"""The real mechanism bundle — everything the agent can physically do.

Each verb delegates to a registered plugin rather than implementing anything
itself, so adding a mitigation or a validation source never touches this file:

    detect_incidents  -> every registered Detector
    read_context      -> DataHub graph
    run_checks        -> every applicable CheckRunner, ANDed
    act / undo        -> the Actuator registered for that ActionType
    propose_fix       -> CodeFixTool
    write_back        -> DataHubWriteBack (+ the injected MemoryStore)

`act` never lets an actuator's failure look like success: an action that raises
is journaled as failed and returned with no inverse, so the caller can see that
the mitigation is incomplete and let the validation gate decide what to do about
it. That honesty is the whole point — the previous implementation reported
mitigations it had not performed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from agent.contracts import (
    ActionRecord,
    ActionType,
    ContextBundle,
    Incident,
    Mechanisms,
    MemoryStore,
    PostMortem,
    ShadowResult,
    ValidationResult,
)
from agent.journal import ActionJournal
from agent.llm import LLMClient
from agent.registry import build_actuators, build_checks, build_detectors
from agent.tools.codefix.generator import CodeFixTool
from agent.tools.graph.context import DataHubContextTool
from agent.tools.graph.writeback import DataHubWriteBack

# import plugin packages so their decorators register
import agent.tools.actuators  # noqa: F401
import agent.tools.checks  # noqa: F401
import agent.tools.detectors  # noqa: F401
import agent.tools.probes  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[3]


class RealMechanisms(Mechanisms):
    def __init__(self, gms_server: str = "http://localhost:8080",
                 llm: Optional[LLMClient] = None,
                 memory: Optional[MemoryStore] = None,
                 journal: Optional[ActionJournal] = None) -> None:
        self.gms_server = gms_server
        self.context = DataHubContextTool(gms_server)
        self.detectors = build_detectors(gms_server)
        self.checks = build_checks(gms_server)
        self.actuators = build_actuators(gms_server)
        self.codefix = CodeFixTool(llm=llm)
        self.memory = memory
        self.journal = journal or ActionJournal()
        self.writeback = DataHubWriteBack(gms_server, memory=memory)
        # set by the orchestrator so write_back can reach downstream assets
        self.last_context: Optional[ContextBundle] = None

    # --- detection & context ------------------------------------------- #
    def detect_incidents(self) -> list[Incident]:
        incidents: list[Incident] = []
        for d in self.detectors:
            try:
                incidents.extend(d.detect())
            except Exception as e:
                print(f"  [detect   ] detector {d.name} failed: "
                      f"{type(e).__name__}: {e}")
        return incidents

    def read_context(self, asset_urn: str) -> ContextBundle:
        ctx = self.context.read_context(asset_urn)
        self.last_context = ctx
        return ctx

    # --- validation gate ------------------------------------------------ #
    def run_checks(self, asset_urn: str) -> ValidationResult:
        """Run every check that applies and AND the verdicts.

        More than one has to agree, because they see different things: dbt tests
        catch broken values, the model check catches a bad champion, and the
        invariant check catches the failures that leave both of those green.
        """
        applicable = [c for c in self.checks if _applies(c, asset_urn)]
        if not applicable:
            return ValidationResult(
                passed=False, checks_run=[],
                failures=[f"no validation check covers {asset_urn} — refusing to "
                          f"certify a mitigation nothing verified"],
            )

        checks_run: list[str] = []
        failures: list[str] = []
        for c in applicable:
            try:
                result = c.run(asset_urn)
            except Exception as e:
                failures.append(f"{c.name}: check errored ({type(e).__name__}: {e})")
                continue
            checks_run.extend(result.checks_run or [c.name])
            failures.extend(result.failures)

        return ValidationResult(passed=not failures, checks_run=checks_run,
                                failures=failures)

    # --- act / undo ----------------------------------------------------- #
    def act(self, action: ActionRecord) -> ActionRecord:
        actuator = self.actuators.get(action.action_type)
        if actuator is None:
            action.status = "failed"
            self.journal.record_failed(action, action.incident_id,
                                       "no actuator registered")
            return action
        try:
            applied = actuator.apply(action)
        except Exception as e:
            action.status = "failed"
            action.inverse = None
            self.journal.record_failed(action, action.incident_id,
                                       f"{type(e).__name__}: {e}")
            return action
        return self.journal.record_applied(applied, applied.incident_id)

    def undo(self, action: ActionRecord) -> bool:
        actuator = self.actuators.get(action.action_type)
        if actuator is None:
            return False
        try:
            return actuator.revert(action)
        except Exception as e:
            print(f"  [rollback ] {action.action_type.value} on "
                  f"{action.target}: {type(e).__name__}: {e}")
            return False

    def rollback(self, incident_id: str,
                 mutating_only: bool = False) -> tuple[int, int]:
        """Undo what an incident applied, newest first.

        `mutating_only` withdraws the actions that changed data or what is
        serving, while leaving the protective ones — tags and breakers — in
        place. A repair that failed validation is a reason to keep downstream
        consumers warned off, not to stop warning them.
        """
        only = None
        if mutating_only:
            from agent.policy import AutonomyPolicy

            only = lambda a: not AutonomyPolicy.is_protective(a.action_type)  # noqa: E731
        return self.journal.undo_all(incident_id, self.undo, only=only)

    def release_containment(self, incident_id: str) -> tuple[int, int]:
        """Lift the protective measures once the incident is genuinely fixed.

        The circuit breaker has to close itself. A repair that leaves the scoring
        job paused and the downstream assets flagged has not really finished —
        and a human clearing them by hand every time is how people learn to
        ignore the flags.
        """
        from agent.policy import AutonomyPolicy

        return self.journal.undo_all(
            incident_id, self.undo,
            only=lambda a: AutonomyPolicy.is_protective(a.action_type),
        )

    # --- fix & close ---------------------------------------------------- #
    def propose_fix(self, incident: Incident, context: ContextBundle,
                    root_cause: str) -> str:
        return self.codefix.propose_fix(incident, context, root_cause)

    def write_back(self, post_mortem: PostMortem, resolved: bool = True) -> None:
        self.writeback.write_back(post_mortem, self.last_context, resolved=resolved)

    # --- fire drill & shadow validation --------------------------------- #
    def inject_failure(self, scenario_name: str) -> Optional[Incident]:
        """Break something on purpose and return the incident it produced.

        The pass condition comes from the scenario's own declared expectation, so
        a drill checks that the agent noticed *the right thing* rather than
        merely noticing something.
        """
        from agent.tools.mechanisms.injector import FailureInjector, first_matching

        injector = FailureInjector()
        if not injector.inject(scenario_name):
            return None
        expected = injector.expected_signal(scenario_name)
        return first_matching(self.detect_incidents(), expected)

    def shadow_validate(self, incident: Incident, fix: str) -> ShadowResult:
        """Evaluate a candidate somewhere it cannot affect production.

        `fix` is either a model version to try, or a path to a generated file.
        """
        from agent.tools.warehouse.shadow import ShadowEnvironment

        shadow = ShadowEnvironment()
        if fix.endswith(".py"):
            path = REPO_ROOT / fix
            if not path.exists():
                return ShadowResult(passed=False, checks_run=["syntax"],
                                    failures=[f"{fix} does not exist"])
            return shadow.verify_python(
                fix, path.read_text(encoding="utf-8", errors="ignore"))

        current = self.actuators.get(ActionType.REPOINT_MODEL)
        current_version = (current.champion.current().version
                           if current and current.champion.current() else "")
        return shadow.compare_versions(current_version, fix)


def _applies(check, asset_urn: str) -> bool:
    try:
        return bool(check.applies_to(asset_urn))
    except Exception:
        return False
