"""Entry point:  python -m agent [--fake]

Runs the Sentinel remediation loop.

  default   real DataHub-backed detection + context (run a scenario first to
            create an incident), with LLM RCA if OPENROUTER_API_KEY is set.
  --fake    fully canned run (no DataHub / no key needed) — always shows a full
            loop, useful for a quick smoke test.
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

    ap = argparse.ArgumentParser(prog="agent")
    ap.add_argument("--fake", action="store_true", help="use canned mechanisms")
    args = ap.parse_args()

    llm = LLMClient()
    if llm.available():
        print(f"LLM: {llm.model} (via OpenRouter)")
    else:
        print("LLM: not configured (set OPENROUTER_API_KEY) — using RCA fallback")

    if args.fake:
        from agent.tools.mechanisms.fakes import FakeMechanisms

        mechanisms = FakeMechanisms()
        memory = None
    else:
        from agent.tools.mechanisms.composite import RealMechanisms
        from memory.base import get_memory

        memory = get_memory()  # DataHub-backed incident memory
        # llm powers the CodeFixTool; memory is where write_back records
        mechanisms = RealMechanisms(llm=llm, memory=memory)

    SentinelAgent(mechanisms, llm=llm, memory=memory).run()


if __name__ == "__main__":
    main()
