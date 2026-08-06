# Sentinel — the autonomous on-call ML engineer

> Detection is commoditized. Sentinel does **remediation**: it root-causes ML pipeline
> incidents across DataHub's end-to-end lineage, applies a **reversible** fix, verifies it,
> rolls itself back if the fix fails, and writes the post-mortem back into the graph so the
> next incident resolves faster.

Built for the **DataHub Agent Hackathon** — Track 3: Production ML Agents.

## The problem

A broken dashboard *looks* broken. A drifting model happily serves wrong predictions for
weeks. Observability tools (Monte Carlo, Arize, Fiddler) tell you something broke — none of
them fix it. Sentinel closes the loop:

```
detect → root-cause (walk ML lineage) → blast radius → apply reversible fix
→ validate → keep & write post-mortem  |  auto-rollback & escalate → learn
```

## Why DataHub is load-bearing

Remove DataHub and the agent is blind and amnesiac:

- **The unified graph** — the only place `source table → feature → model → deployment`
  lineage exists in one map. Sentinel's whole root-cause walk runs on it.
- **Shared memory** — post-mortems are written back onto the **model card**, so the next
  agent or engineer inherits the knowledge. This is the moat: the graph gets smarter with
  every incident.
- **Control plane** — DataHub tags (`Tier-Critical`, `PII`) drive the agent's autonomy tier.

## Architecture

Mechanism / policy split (see `contracts.py` — the interface between the two planes):

- **Mechanism plane** — DataHub adapter, snapshot/model-version engine, dbt runner, GitHub.
  *Things the system can do.*
- **Policy plane** — orchestrator loop, RCA, rollback controller, validation gate, memory.
  *What the system decides to do, and how to undo it.*

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
datahub docker quickstart          # brings up DataHub at http://localhost:9002
cp .env.example .env               # then fill in keys
```

Full setup and demo walkthrough: _coming as the build lands._

## Status

Early build. Phase 0 (scaffold) complete. See `examples/` for sample outputs.

## License

Apache 2.0 — see [LICENSE](LICENSE).
