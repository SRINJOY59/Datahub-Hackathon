"""Entry point:  python -m agent [command] [options]

    python -m agent                 run the remediation loop against live DataHub
    python -m agent --fake          canned run, no DataHub or API key needed
    python -m agent --shadow        reason to a plan and record it, change nothing
    python -m agent digest          what the agent did, or would have done
    python -m agent badges          recompute the health grade on every asset
    python -m agent runbooks        synthesise runbooks from resolved incidents
    python -m agent notify          write role-tailored comms for open incidents
    python -m agent drill <name>    fire drill: break it on purpose, then heal it
    python -m agent serve           start the webhook server (event-driven mode)

Run a scenario first (`python -m scenarios <name>`) to give the loop something to
find, or use `drill` to do both in one step.
"""
from __future__ import annotations

import argparse

from agent.console import enable_utf8
from agent.llm import LLMClient
from agent.orchestrator import SentinelAgent


def main() -> None:
    enable_utf8()
    try:
        from dotenv import load_dotenv

        load_dotenv()  # pick up OPENROUTER_API_KEY from .env if present
    except ImportError:
        pass

    args = _parse_args()

    if args.command == "digest":
        return _digest()

    llm = LLMClient()
    if llm.available():
        print(f"LLM: {llm.model} (via OpenRouter)")
    else:
        print("LLM: not configured (set OPENROUTER_API_KEY) — using RCA fallback")

    if args.command == "badges":
        return _badges()
    if args.command == "runbooks":
        return _runbooks(llm)
    if args.command == "serve":
        return _serve(llm)

    agent, mechanisms = _build_agent(args, llm)

    if args.command == "notify":
        return _notify(agent)
    if args.command == "drill":
        return _drill(agent, mechanisms, args.scenario)

    if args.shadow:
        print("SHADOW MODE — the agent will decide what to do and record it, "
              "but change nothing.\n")
    agent.run()
    if args.shadow:
        _digest()


# --------------------------------------------------------------------------- #
def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="agent")
    ap.add_argument("command", nargs="?", default="run",
                    choices=["run", "digest", "badges", "runbooks", "notify", "drill", "serve"],
                    help="what to do (default: run the loop)")
    ap.add_argument("scenario", nargs="?", help="scenario name, for `drill`")
    ap.add_argument("--fake", action="store_true", help="use canned mechanisms")
    ap.add_argument("--shadow", action="store_true",
                    help="plan and record without applying anything")
    return ap.parse_args()


def _build_agent(args, llm) -> tuple[SentinelAgent, object]:
    if args.fake:
        from agent.tools.mechanisms.fakes import FakeMechanisms

        mechanisms, memory = FakeMechanisms(), None
    else:
        from agent.tools.mechanisms.composite import RealMechanisms
        from memory.base import get_memory

        memory = get_memory()
        mechanisms = RealMechanisms(llm=llm, memory=memory)

    notifier = _get_notifier()
    pager = _get_pager()
    agent = SentinelAgent(mechanisms, llm=llm, memory=memory, shadow=args.shadow,
                          notifier=notifier)
    agent.pager = pager
    return agent, mechanisms


def _get_notifier():
    try:
        from agent.integrations.slack import shared_slack
        return shared_slack()
    except Exception:
        return None


def _get_pager():
    try:
        from agent.integrations.pagerduty import shared_pagerduty
        return shared_pagerduty()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
def _digest() -> None:
    from agent.reporting.digest import SavingsDigest

    print(SavingsDigest().build().render())


def _badges() -> None:
    """Recompute every asset's health grade, whether or not anything broke."""
    from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig

    from agent.tools.graph.trust import TrustScorer

    graph = DataHubGraph(DataHubGraphConfig(server="http://localhost:8080"))
    scorer = TrustScorer()
    urns = list(graph.get_urns_by_filter(entity_types=["dataset"], platform="dbt"))

    print(f"\nScoring {len(urns)} asset(s):\n")
    for urn in sorted(urns):
        score = scorer.score_and_publish(urn)
        name = urn.split(",")[1].split(".")[-1] if "," in urn else urn
        print(f"  {name:24s} {score.grade}  {score.score:5.1f}   {score.inputs}")


def _runbooks(llm) -> None:
    from agent.knowledge.runbook import MIN_INCIDENTS, RunbookSynthesizer

    synth = RunbookSynthesizer(llm=llm)
    grouped = synth.collect()
    if not grouped:
        print("\nNo post-mortems recorded yet — resolve some incidents first.")
        return

    print("\nPost-mortems on record:")
    for change_type, incidents in sorted(grouped.items()):
        enough = "" if len(incidents) >= MIN_INCIDENTS else "  (need 2+ to generalise)"
        print(f"  {change_type:24s} {len(incidents)}{enough}")

    registered = synth.run()
    if not registered:
        print("\nNothing with enough history to write a runbook from yet.")
        return
    print()
    for change_type, urn, count in registered:
        print(f"  registered runbook for {change_type} "
              f"(from {count} incidents) -> {urn}")


def _notify(agent: SentinelAgent) -> None:
    """For every open incident, write the three role-tailored messages.

    Prints the messages to stdout AND posts them to Slack when configured.
    """
    from agent.reporting.comms import compose
    from agent.reporting.cost import CostEstimator

    incidents = agent.m.detect_incidents()
    if not incidents:
        print("\nNo open incidents to notify about.")
        return

    estimator = CostEstimator()
    notifier = agent.notifier
    print(f"\n{len(incidents)} open incident(s):")
    for inc in incidents:
        ctx = agent.m.read_context(inc.asset_urn)
        rca = agent.rca.analyze(inc, ctx)
        cost = estimator.estimate(ctx, rca.change_type.value)
        messages = compose(inc, ctx, rca, cost)
        print(f"\n{'=' * 70}\n=== {inc.id}: {inc.summary} ===")
        print(messages.render())
        if notifier:
            notifier.announce(inc, ctx, rca, cost)


def _serve(llm) -> None:
    """Start the webhook server — event-driven agent runs."""
    import uvicorn

    from agent.integrations.webhooks.config import WebhookConfig
    from agent.integrations.webhooks.router import AgentRunRequest
    from agent.integrations.webhooks.server import app, configure

    cfg = WebhookConfig.load()
    if not cfg.enabled:
        print("\nWebhook server is disabled (set enabled: true in "
              "config/webhooks.yaml)")
        return

    notifier = _get_notifier()
    pager = _get_pager()

    from agent.tools.mechanisms.composite import RealMechanisms
    from memory.base import get_memory

    memory = get_memory()
    mechanisms = RealMechanisms(llm=llm, memory=memory)

    agent = SentinelAgent(mechanisms, llm=llm, memory=memory, notifier=notifier)
    agent.pager = pager

    def run_agent(request: AgentRunRequest) -> None:
        print(f"\n  [webhook  ] incoming {request.source} event "
              f"-> {request.asset_urn}")
        incidents = agent.m.detect_incidents()
        matched = [i for i in incidents if i.asset_urn == request.asset_urn]
        if not matched and request.asset_urn == "__git_push__":
            matched = incidents
        if matched:
            for inc in matched:
                agent.handle(inc)
        else:
            print(f"  [webhook  ] no open incident for {request.asset_urn} — "
                  f"running full sweep")
            agent.run()

    configure(cfg, run_agent)

    sweep_minutes = cfg.sweep_interval_minutes
    if sweep_minutes > 0:
        import threading

        def _sweep_loop():
            import time
            while True:
                time.sleep(sweep_minutes * 60)
                print(f"\n  [sweep    ] periodic sweep ({sweep_minutes}m interval)")
                try:
                    agent.run()
                except Exception as exc:
                    print(f"  [sweep    ] error: {exc}")

        t = threading.Thread(target=_sweep_loop, daemon=True)
        t.start()

    enabled_sources = [s for s, sc in cfg.sources.items() if sc.enabled]
    print(f"\nWebhook server starting on http://{cfg.server.host}:{cfg.server.port}")
    print(f"  Sources: {', '.join(enabled_sources)}")
    print(f"  Workers: {cfg.server.workers}")
    if sweep_minutes > 0:
        print(f"  Sweep: every {sweep_minutes}m")
    else:
        print(f"  Sweep: disabled")
    print(f"\nEndpoints:")
    for source in enabled_sources:
        print(f"  POST /webhook/{source}")
    print(f"  GET  /health")
    print(f"  GET  /runs\n")

    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port,
                log_level="info")


def _drill(agent: SentinelAgent, mechanisms, scenario: str | None) -> None:
    """Break the pipeline on purpose and watch the agent handle it.

    An agent nobody has seen fail is an agent nobody should trust, so this is
    re-runnable on demand rather than something demonstrated once.
    """
    from agent.tools.mechanisms.injector import FailureInjector

    available = FailureInjector().available()
    if not scenario:
        print(f"\nUsage: python -m agent drill <scenario>\n\n"
              f"  available: {', '.join(available)}")
        return
    if scenario not in available:
        print(f"\nUnknown scenario '{scenario}'. Available: {', '.join(available)}")
        return

    inject = getattr(mechanisms, "inject_failure", None)
    if inject is None:
        print("\nThis mechanism bundle cannot inject failures.")
        return

    print(f"\n=== FIRE DRILL: {scenario} ===\n")
    incident = inject(scenario)
    if incident is None:
        print(f"\nDRILL FAILED — the agent did not detect the incident "
              f"'{scenario}' was supposed to cause.")
        raise SystemExit(1)

    print(f"\n  [drill    ] detected as expected: {incident.signal_type.value}")
    agent.handle(incident)
    print(f"\n=== DRILL COMPLETE — reset with `python -m scenarios reset` ===")


if __name__ == "__main__":
    main()
