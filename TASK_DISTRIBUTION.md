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
| Core LLM client (`agent/llm.py`, OpenRouter) + structured output | ✅ |
| Extensible investigation platform: Detector/Probe/Memory plugin registries | ✅ |
| Grounded RCA engine (`agent/rca.py`) — probes + memory + structured synthesis | ✅ |
| Pluggable memory: `DataHubMemory` (record/recall) + `CodebaseMemory` | ✅ |

### Incident classes implemented (each a Detector + Probe plugin)

| Class | Detector / Probe | Status |
|---|---|---|
| Data (assertion + profiling) | DataHubAssertion / DataProfile + ColumnLineage | ✅ |
| Dependency / API break ("self-maintaining APIs") | DependencyChange / DependencyImpact + CodeFixTool | ✅ |
| ML training regression | TrainingMetric / ModelEval | ✅ |
| Model drift / freshness / git-commit | — | ⬜ (new plugins) |

---

## Srinjoy — Mechanism plane

Implements the 6 `Mechanisms` functions with real DataHub / MLflow / dbt / git,
plus the mechanism-side features.

### Core tools (the contract)

| Fn / Tool | Feature | Status |
|---|---|---|
| `detect_incidents()` | multi-detector registry: assertions + dependency + training | ✅ |
| `read_context()` | real lineage / schema / tags / owners | ✅ |
| `run_checks()` | real dbt test / assertion re-run (validation gate) | ⬜ |
| `act()` / `undo()` | **#1 Time Machine** — MLflow stage swap + feature pin, journaled with inverses | ⬜ |
| `write_back()` | **#4 Circuit Breaker** — open incident, tag downstream "degraded", auto-restore | ⬜ |
| `propose_fix()` | **CodeFixTool** — LLM-generated migration diff + draft PR | ✅ |

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

---

# Product Roadmap — what makes this a real product

The current build proves **detection + grounded RCA + fix generation** across
three incident classes. To become a product a data/ML/platform team pays for, the
gaps are actuation (safe, reversible fixes), coverage (more signals + warehouses),
and the product surface (comms, dashboard, autonomy controls). Everything below is
a candidate; MVP-critical items are marked ⭐.

Status: ✅ done · 🔨 partial · ⬜ not started

## 1. Remediation & actuation (the trust layer — highest priority)
The intelligence is real; the *actions* are still stubbed. This is what converts
"an agent that explains" into "an agent that fixes."

- ⭐ **Time Machine** ⬜ — real reversible mitigations: MLflow champion repoint to
  last-good version, feature-table pinning to a snapshot, view-swap. Every action
  journaled with its inverse.
- ⭐ **Validation gate** ⬜ — real `run_checks` (re-run dbt tests / model eval) after
  a fix; **auto-rollback via the journal if it fails**. This closed loop is the
  core safety story.
- ⭐ **Circuit Breaker** ⬜ — tag downstream assets "do-not-trust" in DataHub, pause
  dependent jobs (Airflow/Dagster), auto-restore on resolution.
- **Quarantine / backfill** ⬜ — isolate a bad partition; trigger a corrected backfill.
- **Real multi-file / multi-repo PRs** 🔨 — CodeFixTool opens single-file PRs today;
  extend to multi-file migrations, run the test suite on the fix, and scan across
  many repos in an org.
- **Fix verification** ⬜ — apply the generated migration in a sandbox and run tests
  before proposing (Parallel-Universe / shadow validation).

## 2. Detection — more signal sources (Detector plugins)
- ⭐ **Model-drift detector** ⬜ — prediction-distribution shift from the scoring loop
  (pairs with `distribution_drift`, catches silent model rot with no assertion).
- ⭐ **Freshness / SLA detector** ⬜ — stale tables / late pipelines.
- **Git-commit detector** ⬜ — a commit to a transform/model/prompt as a signal.
- **Real dependency diff** 🔨 — diff `requirements`/`poetry.lock` over time (today
  we read hand-authored advisories); ingest vendor changelogs / GitHub releases /
  OpenAPI-spec diffs to auto-derive breaking changes.
- **Orchestrator failure detector** ⬜ — Airflow/Dagster/Prefect task failures.
- **External observability import** ⬜ — Monte Carlo / Great Expectations / Soda
  signals as detectors.
- **Cost/spend anomaly detector** ⬜ — warehouse spend spikes.

## 3. Investigation — more probes (Probe plugins)
- **Schema-history / timeline probe** ⬜ — DataHub timeline API: exactly what changed
  and when (pin the change to a timestamp → correlate to a commit/deploy).
- **Git-blame probe** ⬜ — the exact commit + author behind a change (Drift Attribution).
- **Training/serving-skew probe** ⬜ — feature distributions at train vs serve time.
- **Cross-incident correlation** 🔨 — basic same-root dedupe exists; add semantic
  clustering of simultaneous incidents to one root cause.
- **LLM-pipeline probes** ⬜ — prompt-template diff, tokenizer/config change, eval-set
  regression, dataset contamination, RAG retrieval-quality checks.

## 4. Memory & knowledge (the compounding moat)
- **Vector memory** ⬜ — embeddings for semantic recall of similar past incidents
  (today: same-asset + same-change-type filter).
- **Runbook → DataHub Skill** ⬜ — synthesize a runbook from repeated incidents and
  register it as a Skill (also the OSS-contribution tiebreaker).
- **CodebaseMemory → DataHub** ⬜ — ingest code files as assets so code↔data lineage
  lives in the graph, not just in-process.
- **MTTR / learning analytics** ⬜ — track resolution time trending down as memory grows.

## 5. Autonomy, policy & governance
- **Tiered autonomy** 🔨 — tag-driven auto / PR-only / human today; expand with
  blast-radius- and confidence-based gating.
- ⭐ **Shadow mode + savings digest** ⬜ — propose-only mode with "would have resolved
  N incidents, saved M hours" — the enterprise adoption on-ramp.
- **Human-in-the-loop approvals** ⬜ — approve/deny an action from Slack.
- **Audit log** ⬜ — every agent action + its inverse, immutable and reviewable.

## 6. Product surface (what users actually touch)
- ⭐ **Slack/Teams integration** ⬜ — incident channel, audience-aware messages
  (engineer vs analyst vs exec), approve-from-chat.
- ⭐ **Web dashboard** ⬜ — incident list, timeline, RCA, blast radius, MTTR.
- **Cost-of-incident meter** ⬜ — $ impact from blast radius × usage.
- **Trust badges / health scores** ⬜ — live reliability score written onto DataHub assets.
- **Ask-the-on-call** ⬜ — chat over incident memory.
- **Paging** ⬜ — PagerDuty / Opsgenie for human-tier incidents.

## 7. Platform & enterprise readiness
- **Multi-warehouse** ⬜ — Snowflake / BigQuery / Databricks / Redshift (today: DuckDB).
- **Scale** ⬜ — async job queue, many concurrent incidents, rate-limited LLM calls.
- **Multi-tenancy / RBAC / auth** ⬜.
- **Deployment** ⬜ — containerized service, scheduled runs, webhook triggers.
- **Connectors** ⬜ — dbt Cloud, Fivetran, Airflow, GitHub App install.

## 8. The self-maintaining-API wedge (YC framing)
The dependency/API vertical is the sharpest standalone product ("Dependabot for APIs").
- **Vendor changelog tracking** ⬜ — monitor SDK releases / OpenAPI diffs to derive
  breaking changes automatically (today: hand-authored advisories).
- **Per-provider agents** ⬜ — "install Stripe's update agent."
- **Neutral third-party service** ⬜ — track changes across many vendors, scan customer
  repos, open PRs.
- **Org-wide repo scanning** ⬜ — one advisory → PRs across every affected repo.

## Suggested build order (post-hackathon → product)
1. ⭐ Time Machine + validation gate + auto-rollback (real actuation, the trust core).
2. ⭐ Circuit Breaker + Slack integration (visible remediation + product surface).
3. ⭐ Model-drift + freshness detectors (coverage of the most common silent failures).
4. Shadow mode + savings digest + dashboard (enterprise adoption on-ramp).
5. Vector memory + runbook→Skill (the compounding moat + OSS contribution).
6. Multi-warehouse + deployment + connectors (make it installable).
