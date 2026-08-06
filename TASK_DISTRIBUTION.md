# Task Distribution — Sentinel

Two builders, split by **interface, not by feature**, so we work in parallel and
only integrate at the seam.

- **Srinjoy** owns the **Mechanism plane** — the backbone and everything that
  physically touches DataHub, the warehouse, MLflow, git, and snapshots. *Things
  the system can do.*
- **Arkajyoti** owns the **Intelligence plane** — features that consume the
  agent's outputs (incidents, context, post-mortems) to reason, communicate,
  quantify, and remember. *What the system says, scores, and learns.*

The seam is `agent/contracts.py` (the 5 data objects + the `Mechanisms`
interface). Arkajyoti builds against these types and the fake tool bundle
(`agent/tools/fakes.py`); Srinjoy replaces the fakes with real tools underneath.
Neither side edits the other's modules.

Legend: ✅ done · 🔨 in progress · ⬜ todo

---

## Shared foundation (done — Srinjoy)

| Component | Status |
|---|---|
| Environment: DataHub quickstart, dbt+DuckDB pipeline, MLflow model + scoring | ✅ |
| Ingestion + end-to-end lineage + governance (tags/owners) | ✅ |
| Incident scenarios (`unit_bug`, `null_spike`, `reset`) as classes | ✅ |
| `contracts.py` (data objects + `Mechanisms` interface) + `fakes.py` | ✅ |
| Orchestrator loop (`agent/orchestrator.py`) | ✅ |
| Core LLM client (`agent/llm.py`, OpenRouter) — shared infra | ✅ |

---

## Srinjoy — Mechanism plane

Implements the 6 `Mechanisms` functions with real DataHub / MLflow / dbt / git,
plus the mechanism-side features.

### Core tools (the contract)

| Fn / Tool | Feature | Status |
|---|---|---|
| `detect_incidents()` | assertion-failure detection from DataHub | ✅ |
| `read_context()` | real lineage / schema / tags / owners | ✅ |
| `run_checks()` | real dbt test / assertion re-run (validation gate) | ⬜ |
| `act()` / `undo()` | **#1 Time Machine** — MLflow stage swap + feature pin, journaled with inverses | ⬜ |
| `write_back()` | **#4 Circuit Breaker** — open incident, tag downstream "degraded", auto-restore | ⬜ |
| `propose_fix()` | draft fix PR against the real schema (GitHub) | ⬜ |

### Mechanism-side features

| # | Feature | Status |
|---|---|---|
| 1 | **Time Machine** — one-click reversible rollback (via `act`/`undo`) | ⬜ |
| 4 | **Smart Circuit Breaker** — tag/quarantine downstream + auto-restore | ⬜ |
| 2 | **Drift Attribution** — walk lineage upstream, correlate to the breaking commit | ⬜ |
| 3 | **Parallel Universe / Shadow Scoring** — apply fix in a clone, diff before/after as PR proof | ⬜ |
| 11 | **Fire Drill** — `inject_failure()` mechanism (orchestration handed to Arkajyoti) | ⬜ |

Build order: `run_checks` → **Time Machine** → **Circuit Breaker** →
**Drift Attribution** → Parallel Universe. Cut from the bottom if time runs short.

---

## Arkajyoti — Intelligence plane

Consumes `Incident`, `ContextBundle`, and `PostMortem` through the contract.
Builds entirely against `fakes.py` until Srinjoy's real tools land — no blocking.

| # | Feature | What it needs from the contract | Status |
|---|---|---|---|
| 5 | **Organizational Memory** — post-mortems embedded on the model card; incident #2 resolves faster by citing #1 | `PostMortem` objects the loop emits | ⬜ |
| 6 | **Audience-Aware Comms** — one incident → 3 tailored messages (ML eng / data scientist / product) | `ContextBundle.owners`, `tags` | ⬜ |
| 7 | **Cost-of-Incident Meter** — $ estimate from blast radius × usage ("~$12K exposure") | `ContextBundle.downstream` + usage stats | ⬜ |
| 8 | **Shadow Mode + Savings Digest** — "this week I *would have* resolved N incidents, saved M hours" | the action journal | ⬜ |
| 9 | **Trust Badges** — live model-health score written onto assets in DataHub | calls Srinjoy's `write_back` helper | ⬜ |
| 10 | **Runbook → DataHub Skill** — synthesize a runbook, register as a Skill (also the OSS-contribution PR) | Memory (#5) + Srinjoy wires Skill registration | ⬜ |
| 12 | **Ask the On-Call** — chat over incident memory | Memory (#5) | ⬜ |
| — | **RCA prompt quality** — refine `agent/prompts/rca.py` and structured-output parsing | LLM client (shared) | 🔨 |
| 11 | **Fire Drill orchestration** — drive Srinjoy's `inject_failure()` to prove self-healing (stretch) | `inject_failure()` | ⬜ |

Priority: **Memory (#5) first** — it's the moat, and #10 and #12 depend on it.
Then Comms (#6), Cost Meter (#7), Trust Badges (#9). Shadow Digest (#8) and
Ask-the-On-Call (#12) are first cuts. Skill synthesis (#10) never gets cut — it's
the OSS tiebreaker.

---

## Integration points (when we must sync)

1. **Contract is frozen** — `agent/contracts.py` is the treaty. Any change to a
   data object or function signature is a two-person decision.
2. **Integration pass** — Arkajyoti swaps `FakeMechanisms` for `RealMechanisms`
   as Srinjoy's tools land, one function at a time. Do this early and often, not
   the night before.
3. **Skill registration** — Arkajyoti drafts the runbook Skill content; Srinjoy
   wires the DataHub Skill registration.
4. **Submission** — split the video (demo the break → detect → RCA → restore
   loop) and the README/examples together.
