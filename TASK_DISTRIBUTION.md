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

## Build phases

Work ships one phase at a time. Each phase ends with a written review, updates to
this file and the README, and a commit — nothing starts until the previous phase
is signed off.

| Phase | Scope | Status |
|---|---|---|
| **0** | Structural repairs + foundation modules (behaviour-neutral) | ✅ |
| **1** | Real mechanisms: `run_checks` / `act` / `undo` / `write_back`, planner + policy | ✅ |
| **2** | Six new threat classes (detectors, probes, scenarios) | ✅ |
| **3** | Drift Attribution, Fire Drill, Parallel Universe, Shadow Mode, Trust Badges, Runbook→Skill | ✅ |
| **4** | Verification: `scenarios verify` matrix (each scenario run through the agent, checked against its `Expectation`) | ✅ |
| **5** | Cost meter, MCP Server reads, git-commit detector, structured `IncidentOutcome` + contract cleanup | ✅ |
| **6** | Intelligence-plane UI & Ops: Full Web Dashboard, Pipeline Observability, Ask-the-On-Call with Markdown citations, scripts/seed_incidents.py modularization | ✅ |

### Who each phase serves

| Phase | Srinjoy (Mechanism) | Arkajyoti (Intelligence) |
|---|---|---|
| 0 | contract, registries, journal, snapshots, dbt/model/git readers | `ActionJournal` for #8; `source_file_for()` for #2; RCA enum-parity fix |
| 1 | `run_checks`, `act`/`undo`, `write_back`, planner + policy, **#1**, **#4** | **#5** post-mortems on the model card + precedent recall |
| 2 | 6 detectors + probes; RCA signal→change-type map | RCA prompt quality; richer `PostMortem` corpus for #10 |
| 3 | **#2** Drift Attribution, **#3** Parallel Universe, **#11** `inject_failure()` | **#8** Shadow Mode, **#9** Trust Badges, **#10** Runbook→Skill |
| 4 | scenario expectation harness | **#11** fire-drill orchestration via `verify --all` |
| 5 | git-commit detector, MCP server, `IncidentOutcome` | cost-of-incident estimator, Slack/PagerDuty notification formatting |
| 6 | `scripts/seed_incidents.py` modularization, pipeline observability data | Next.js Dashboard (`/`, `/incidents`, `/pipeline`, `/trends`, `/assets`, `/runbooks`, `/activity`), Full Markdown Ask-On-Call chat (`/chat`) |

Neither plane waits on the other: every phase moves both.

### Phase 0 — what landed

*Behaviour-neutral by design: the six existing scenarios behave exactly as before.
This phase built the machinery Phase 1 actuates with.*

| Repair | Why it was needed |
|---|---|
| `BaseScenario` ABC → `DataScenario` / `AdvisoryScenario` / `ModelScenario` | scenarios were three unrelated shapes held together by duck-typing; six more would have made a fourth |
| `PipelineReset` + per-scenario `cleanup()` | `reset()` was a `@staticmethod` on a scenario class and structurally couldn't restore ML-side state |
| `scenarios/registry.py` | the scenario list lived in `__main__.py`; three consumers now need it |
| `@actuator` / `@check` registries, signature-inspecting `_build` | `except TypeError` silently swallowed constructor errors; skipped plugins are now reported |
| `CodebaseMemory.source_file_for()` | the producer map already knew SQL file → asset; Drift Attribution needs it read backwards |
| `RCAResult.change_type` → the `ChangeType` enum | the hand-written `Literal` listed 6 of 9 values, forcing the LLM into a wrong value for the rest. Now 15/15, and drift is impossible |

| New foundation module | Role |
|---|---|
| `agent/journal.py` — `ActionJournal` | append-only action + inverse log at `.sentinel/journal.jsonl`; rollback source, audit trail, and shadow-digest input |
| `agent/tools/warehouse/snapshots.py` | point-in-time table copies; what the Time Machine restores from. Verified exact via content fingerprint |
| `agent/tools/warehouse/dbt_runner.py` | one dbt invocation path; parses `run_results.json` so the gate names failing assertions instead of only knowing something failed |
| `agent/tools/warehouse/baselines.py` | the pipeline's healthy shape — the only way silent failures are visible |
| `agent/tools/warehouse/champion.py` | single MLflow registry read; `last_good()` picks the rollback target |
| `agent/tools/warehouse/duck.py` | retries the transient DuckDB lock held by an exiting dbt subprocess (unplanned; found during verification) |
| `agent/tools/code/git_history.py` | read-only `git log`/`blame` for commit attribution |
| `ml/drift.py` | drift maths shared by the scoring job and the drift detector, so they cannot disagree |

Contract additions were strictly additive: `SignalType` 7→10, `ChangeType` 9→15,
`ActionType` 5→6, plus `ShadowResult`, `TrustScore`, and the `Actuator` /
`CheckRunner` Protocols. No existing field renamed or removed.

### Phase 1 — what landed

*The agent now does what it says it does. `RealMechanisms` no longer delegates
anything to `FakeMechanisms`.*

**Six actuators**, each with a working inverse (`agent/tools/actuators/`):

| Actuator | Real effect | Inverse |
|---|---|---|
| `pin_feature` | restores a table from `last_good`, rebuilds downstream | restore the pre-action snapshot |
| `quarantine` | moves rows outside the healthy range into `sentinel_quarantine.<table>__<incident>` | restore the pre-action snapshot |
| `dedupe_partition` | drops duplicate keys, keeping first arrival | restore the pre-action snapshot |
| `repoint_model` | moves the MLflow `champion` alias to the newest *validated* healthy version | point it back |
| `tag_asset` | adds `Sentinel-Degraded` to downstream assets in DataHub | remove it |
| `pause_job` | opens a breaker file; **`ml/score.py` refuses to score while it is open** | close it |

**Three validation checks**, ANDed (`agent/tools/checks/`): `dbt_tests` (real
assertion results by name), `model_eval` (champion inside a *bounded* metric band
— too high is leakage, not success), and `data_invariants` (volume and freshness
against the recorded baseline, which is the only thing that can see a stale feed
or a collapsed batch, since dbt stays green through both).

**Decision-making extracted from the loop:** `agent/policy.py` and
`agent/planner.py`. The planner is a `ChangeType → recipe` table, so what the
agent will do about a null spike is readable without reading the code that does
it. The policy finally has teeth — `HUMAN_ONLY` now genuinely blocks mutating
actions instead of only adding a PR.

The autonomy model splits actions by what they touch. **Protective** actions
(tag, pause) only ever reduce harm, so they run at every tier — withholding them
while waiting for a human is itself the risky choice. **Mutating** actions (pin,
quarantine, dedupe, repoint) change data or what is serving, and need confidence
behind them. `PII` plus a diagnosis below high confidence is the one combination
that drops to protective-only.

**Two bugs found by verification, not by review:**

- Both warehouse actuators in one plan snapshotted the same restore label, so the
  second silently overwrote the first's way back. A rollback would have restored
  an intermediate state and lost the quarantined rows. Restore points are now per
  *action*, not per incident.
- `python -m ml.score` crashed with `UnicodeEncodeError` whenever its output was
  piped, because Windows selects cp1252 for redirected stdout. Fixed at the entry
  points (`agent/console.py`) rather than by avoiding punctuation.

### Phase 2 — what landed

*Five detectors, six probes, six scenarios. The agent can now see the failures
that leave every assertion green.*

| Threat | Detection | Outcome |
|---|---|---|
| `stale_feed` | `FreshnessDetector` — lag vs the **baseline's** newest row, not wall-clock (the seed data is synthetic and already days old, so a clock check would fire permanently) | **contained** |
| `volume_collapse` | `VolumeAnomalyDetector` — row counts vs baseline | **repaired** (pin) |
| `model_drift` | `ModelDriftDetector` — scoring snapshot vs baseline through `ml/drift.py` | **repaired** (repoint) |
| `training_serving_skew` | `TrainingServingSkewDetector` — serving means vs the champion's `train_mean_*` | **contained** |
| `label_leakage` | `LabelLeakageDetector` — `roc_auc` **above** a ceiling | **repaired** + code fix |
| `duplicate_batch` | reuses `DataHubAssertionDetector` | **repaired** (dedupe) |

**Three of these leave all 22 dbt assertions passing.** That is the point: a
pipeline can be badly wrong while every test it has says otherwise.

**Containment as a first-class outcome.** Some incidents cannot be repaired from
here — data that never arrived cannot be restored from a snapshot. Previously the
gate would go red, and the agent would respond by **reverting the circuit breaker
and letting the pipeline keep serving bad data**. Now a plan made only of
protective actions is recognised as containment: the tags and breaker hold, a
post-mortem is recorded as *contained, awaiting human*, `Sentinel-Resolved` is
withheld, and the incident stays visibly open. When an incident *is* genuinely
repaired, the protection is lifted automatically — a breaker that outlives its
incident is how people learn to ignore breakers.

**Correctness fixes this phase depended on:**

| Fix | What it prevented |
|---|---|
| `SIGNAL_TO_CHANGE` table in `rca.py` | five of six new classes would have been classified `unknown` and received the do-nothing fallback recipe |
| `_asset_urn` / `upstream_path` urn guards | three detectors fire on **mlModel** urns, where the old code invented a dataset urn that does not exist and used it as an action target |
| `ModelInputCheck` | the gate only measured `roc_auc`, which is *fine* during a skew incident — the agent declared victory over a problem it had only contained |
| Selective rollback | see containment above |
| `identify_leaks` — floor **plus** dominance over the runner-up | an absolute correlation threshold either missed the real leak (0.70) or would flag genuinely predictive features |
| `classify()` all-null rule | **latent bug in existing code**: `schema_change` had always resolved to `unknown`/low confidence, because the renamed column still exists and is simply empty |
| `_readable` on the DataHub assertion path | incidents read `1 failed assertion: a321883ce7` |
| champion restore uses the healthy band | `reset` would have reinstated the **leaked** 0.998 model, since every trained version is tagged validated |

### Phase 3 — what landed

*The last six features. Both planes are now complete except the three
Intelligence items deliberately left out of scope.*

| # | Feature | How it works |
|---|---|---|
| **2** | Drift Attribution | `GitBlameProbe` reads `CodebaseMemory`'s producer map **backwards** — the index that maps a source file to the asset it produces already existed for dependency tracing, so an asset resolves to a file and git resolves it to a commit. The RCA narrative now names the author and sha. |
| **11** | Fire Drill | `inject_failure()` on the contract, driven by `python -m agent drill <scenario>`: break it, detect, root-cause, mitigate, validate. The pass condition is the scenario's own declared expectation, so a drill checks the agent noticed *the right thing*. |
| **3** | Parallel Universe | `ShadowEnvironment` scores a candidate model version against today's data **without touching the champion alias**, and parses a generated fix before proposing it. The before/after appears inline in the action note and in the PR body. |
| **8** | Shadow Mode + Digest | `python -m agent --shadow` reasons all the way to a plan and journals it as `simulated`, applying nothing; `python -m agent digest` aggregates the journal into incidents handled and hours saved. |
| **9** | Trust Badges | `TrustScorer` writes a 0-100 score and an A–D grade onto each asset from failing assertions, open incidents, volume and freshness deviation, and incident history. Refreshed on every close — including a contained one, which is when a low grade matters most. |
| **10** | Runbook → Skill | `RunbookSynthesizer` reads back the accumulated post-mortems, generalises the procedure that is already implicit in them, and registers it as a real DataHub **`AgentSkill`** entity with `name` / `description` / `instructions`. |

**On #10:** the plan flagged Skill registration as an open question with a
GlossaryTerm fallback. `AgentSkillInfoClass` turned out to exist in
`acryl-datahub==1.7.0` with exactly the right shape, so no fallback was needed.
One trap: `requiredTools` holds DataHub **urns** despite the name, and rejects
prose — the tool list lives inside `instructions` instead.

**Two bugs found by verification:**

- `TrustScorer` never stored `gms_server`, so its failed-assertion lookup raised
  `AttributeError` into a broad `except` and every asset scored as though its
  tests passed. A **broken pipeline was being graded A.**
- The shadow model comparison failed on incomplete rows — meaning the preview was
  unavailable during exactly the incidents where a rollback gets proposed. It now
  scores the rows it can.

### Phase 4 — what landed

*Every scenario is now an executable test, not something a human eyeballs.*

- **`scenarios/verify.py` + `python -m scenarios verify [name ...]`** — runs each
  scenario through the *real* agent and asserts its declared `Expectation`:
  change-type, root asset/column, actions taken, resolved-vs-contained, and — for
  the silent scenarios — that dbt genuinely stayed green (proving detection did
  not lean on assertions). Nonzero exit on any failure, so it can gate a commit.
- **`handle()` now returns a structured `IncidentOutcome`** (status, change-type,
  root cause, actions, resolved, PR) instead of only printing. The harness — and
  any future API or dashboard — checks that object rather than scraping logs.

### Phase 5 — what landed

*Deeper Use-of-DataHub, an honest cost figure, and the last detector class.*

| Feature | How it works |
|---|---|
| **Reads DataHub via the MCP Server** | `agent/tools/mcp/` — Sentinel reads lineage and schema through the official `mcp-server-datahub` (the same server Claude Desktop/Cursor use), launched isolated via `uvx`, `SENTINEL_USE_MCP=1`, SDK fallback with verified parity. |
| **#7 Cost-of-Incident Meter** | `agent/reporting/cost.py` — measures the real blast radius from the graph and applies rates from a team-owned `config/cost_model.yaml`; the score, inputs and dollar impact are written into the asset's editable description (catalog "About" box), not just a grade tag. Disable-able; cites its assumptions. |
| **Git-commit detector** | `GitCommitDetector` — a commit to a pipeline source is a `CODE_CHANGE` signal, attributed via git and mapped to the impacted asset through `CodebaseMemory`. A human commit is *contained* (downstream flagged, owner paged), not falsely resolved. |
| **`CodebaseMemory` upgraded** | AST-based indexing (robust imports + defined symbols), cached and shared via `shared_codebase()`, O(1) asset→file reverse lookup, enriched producer map, and `pipeline_source_files()`/`defines()`/`symbols_in()`/`all_packages()`. |

**Contract cleanup this phase:** `rollback` / `release_containment` /
`write_back(resolved=)` are now first-class on the `Mechanisms` Protocol (the
orchestrator's `getattr`/`TypeError` compat shims are gone); `PROTECTIVE_ACTIONS`
/ `is_protective` moved next to `ActionType` as the single classifier; added
`CostEstimate` and `IncidentOutcome`. All additive — nothing renamed or removed.

---

## Shared foundation (done — Srinjoy)

| Component | Status |
|---|---|
| Environment: DataHub quickstart, dbt+DuckDB pipeline, MLflow model + scoring | ✅ |
| Ingestion + end-to-end lineage + governance (tags/owners) | ✅ |
| Incident scenarios as a proper class hierarchy + declarative expectations | ✅ |
| `contracts.py` (data objects + `Mechanisms` interface) + `fakes.py` | ✅ |
| Orchestrator loop (`agent/orchestrator.py`) | ✅ |
| Core LLM client (`agent/llm.py`, OpenRouter) + structured output | ✅ |
| Extensible platform: Detector/Probe/**Actuator**/**CheckRunner**/Memory registries | ✅ |
| Grounded RCA engine (`agent/rca.py`) — probes + memory + structured synthesis | ✅ |
| Pluggable memory: `DataHubMemory` (record/recall) + AST-indexed `CodebaseMemory` | ✅ |
| Remediation foundation: journal, snapshots, baselines, dbt/model/git readers | ✅ |
| Reads DataHub via the official **MCP Server** (`agent/tools/mcp/`, SDK fallback) | ✅ |
| Verification harness (`scenarios verify`) + structured `IncidentOutcome` | ✅ |

### Incident classes implemented (each a Detector + Probe plugin)

| Class | Detector / Probe | Status |
|---|---|---|
| Data (assertion + profiling) | DataHubAssertion / DataProfile + ColumnLineage | ✅ |
| Dependency / API break ("self-maintaining APIs") | DependencyChange / DependencyImpact + CodeFixTool | ✅ |
| ML training regression | TrainingMetric / ModelEval | ✅ |
| Model drift · freshness · volume · leakage · skew · duplicates | six Phase-2 detectors + probes | ✅ |
| Git-commit-as-signal | GitCommitDetector + GitBlameProbe | ✅ |

---

## Srinjoy — Mechanism plane

Implements the 6 `Mechanisms` functions with real DataHub / MLflow / dbt / git,
plus the mechanism-side features.

### Core tools (the contract)

| Fn / Tool | Feature | Phase | Status |
|---|---|---|---|
| `detect_incidents()` | multi-detector registry: assertions + dependency + training | pre-phase | ✅ |
| `read_context()` | real lineage / schema / tags / owners | pre-phase | ✅ |
| `run_checks()` | real dbt test / model eval / data invariants, ANDed | **1** | ✅ |
| `act()` / `undo()` | **#1 Time Machine** — 6 actuators, every one journaled with its inverse | **1** | ✅ |
| `write_back()` | **#4 Circuit Breaker** — post-mortem to asset + model card, degraded tags auto-cleared | **1** | ✅ |
| `propose_fix()` | **CodeFixTool** — LLM-generated migration diff + draft PR | pre-phase | ✅ |
| `inject_failure()` | **#11 Fire Drill** — `python -m agent drill <scenario>` | **3** | ✅ |
| `shadow_validate()` | **#3 Parallel Universe** — candidate scoring + fix syntax check | **3** | ✅ |

**Contract coverage: 8/8 complete.**

**Verified against live DataHub, not asserted:** on a `unit_bug` incident the
agent quarantined 1074 real rows, restored `raw_transactions` from 6926 back to
8000, tagged 2 downstream assets, and passed a 29-check gate. Rolling the
incident back returned the table to fingerprint
`8000:74032610348716427358176` — byte-for-byte the poisoned state recorded before
the run — and the assertions failed again, which is the proof the mitigation had
been real. On `training_regression` the champion alias moved v2 → v1.

### Mechanism-side features

| # | Feature | Phase | Status |
|---|---|---|---|
| 1 | **Time Machine** — one-click reversible rollback (via `act`/`undo`) | **1** | ✅ |
| 4 | **Smart Circuit Breaker** — tag/quarantine downstream + auto-restore | **1** | ✅ |
| 2 | **Drift Attribution** — walk lineage upstream, correlate to the breaking commit | **3** | ✅ |
| 3 | **Parallel Universe / Shadow Scoring** — apply fix in a clone, diff before/after as PR proof | **3** | ✅ |
| 11 | **Fire Drill** — `inject_failure()` mechanism | **3** | ✅ |

**Mechanism-side features: 5/5 complete.**

Build order: `run_checks` → **Time Machine** → **Circuit Breaker** →
**Drift Attribution** → Parallel Universe. All five are in the phase plan rather
than cut from the bottom.

### Detector coverage (the incident classes)

| Class | Phase | Status |
|---|---|---|
| Data (assertion + profiling) | pre-phase | ✅ |
| Dependency / API break | pre-phase | ✅ |
| ML training regression | pre-phase | ✅ |
| Model drift | **2** | ✅ |
| Freshness / SLA | **2** | ✅ |
| Volume anomaly | **2** | ✅ |
| Label leakage | **2** | ✅ |
| Duplicate records | **2** | ✅ (reuses the assertion detector; new probe + remediation) |
| Training/serving skew | **2** | ✅ |
| **Git-commit-as-signal** | **5** | ✅ — `GitCommitDetector`, contained + owner paged |

---

## Arkajyoti — Intelligence plane

Consumes `Incident`, `ContextBundle`, and `PostMortem` through the contract.
Builds entirely against `fakes.py` until Srinjoy's real tools land — no blocking.

| # | Feature | What it needs from the contract | Phase | Status |
|---|---|---|---|---|
| 5 | **Organizational Memory** — post-mortems embedded on the model card; incident #2 resolves faster by citing #1 | `PostMortem` objects the loop emits | **1** | ✅ recall + precedent citation working; model-card write landed Phase 1 |
| 8 | **Shadow Mode + Savings Digest** — "this week I *would have* resolved N incidents, saved M hours" | the action journal | **3** | ✅ `python -m agent --shadow` / `digest` |
| 9 | **Trust Badges** — live model-health score written onto assets in DataHub | calls Srinjoy's `write_back` helper | **3** | ✅ `python -m agent badges` |
| 10 | **Runbook → DataHub Skill** — synthesize a runbook, register as a Skill (also the OSS-contribution PR) | Memory (#5) + Skill registration | **3** | ✅ registered as a real `AgentSkill` entity |
| 11 | **Fire Drill orchestration** — drive `inject_failure()` to prove self-healing | `inject_failure()` | **3 + 4** | ✅ `python -m agent drill <scenario>`; matrix in Phase 4 |
| — | **RCA prompt quality** — refine `agent/prompts/rca.py` and structured-output parsing | LLM client (shared) | **0 + 2** | 🔨 enum-parity fix landed Phase 0; signal→change-type map in Phase 2 |
| 7 | **Cost-of-Incident Meter** — $ estimate from the real blast radius × team-owned rates | `ContextBundle.downstream` + `config/cost_model.yaml` | **5** | ✅ written into the catalog "About" box beside the trust grade |
| 6 | **Audience-Aware Comms** — one incident → 3 tailored messages | `ContextBundle.owners`, `tags` | **not scheduled** | ⬜ unblocked, not built |
| 12 | **Ask the On-Call** — chat over incident memory | Memory (#5) | **not scheduled** | ⬜ unblocked, not built |

**Intelligence-plane coverage: 7/9 complete, 2 not scheduled** (#6, #12 —
see below).

### Not scheduled — and why

Two items sit outside the current phase plan. This is a scope decision, not an
oversight, and each is genuinely unblocked: the contract surface it needs already
exists and is exercised by working code.

| Item | What it would need | Why it is unblocked today |
|---|---|---|
| #6 Audience-Aware Comms | a formatter over an incident + its owners | `ContextBundle.owners` / `tags` are real; `PostMortem` carries the narrative and blast radius |
| #12 Ask the On-Call | a chat loop over recalled post-mortems | `MemoryStore.recall()` works and already returns cited precedent |

Each is small precisely because the phases above built the surfaces they consume.
(#7 Cost Meter and the Git-commit detector were on this list; both shipped in
Phase 5.)

---

## Integration points (when we must sync)

1. **Contract is additive-only** — `agent/contracts.py` is the treaty. New enum
   members, dataclasses and Protocols may be added; renaming or removing an
   existing field is a two-person decision. Phase 0 added `SignalType` 7→10,
   `ChangeType` 9→15, `ActionType` 5→6, `ShadowResult`, `TrustScore`, and the
   `Actuator` / `CheckRunner` Protocols — nothing existing changed, so code
   written against the old types still compiles.
2. **Integration pass** — Arkajyoti swaps `FakeMechanisms` for `RealMechanisms`
   as Srinjoy's tools land, one function at a time. Do this early and often, not
   the night before.
3. **Skill registration** — Arkajyoti drafts the runbook Skill content; Srinjoy
   wires the DataHub Skill registration.
4. **Submission** — split the video (demo the break → detect → RCA → restore
   loop) and the README/examples together.

---

# Product Roadmap — what makes this a real product

The current build proves the full loop — **detect → grounded RCA → reversible
remediation → validate → rollback/contain → write-back** — across ~11 incident
classes, with trust badges, a cost meter, verification, and DataHub reads through
the MCP Server. The remaining gaps to a product a data/ML/platform team pays for
are the product surface (comms, dashboard, approvals) and platform readiness
(more warehouses, deployment, scale). Everything below is a candidate; MVP-
critical items are marked ⭐.

Status: ✅ done · 🔨 partial · ⬜ not started

## 1. Remediation & actuation (the trust layer — highest priority)
The intelligence is real; the *actions* are still stubbed. This is what converts
"an agent that explains" into "an agent that fixes."

- ⭐ **Time Machine** ✅ — MLflow champion repoint to the last *validated* version,
  table pinning to a snapshot, quarantine, dedupe. Every action journaled with its
  inverse; rollback verified exact by content fingerprint.
- ⭐ **Validation gate** ✅ — real `run_checks` (dbt tests + model eval + data
  invariants) after a fix, with **auto-rollback via the journal if it fails**.
  The closed loop is the core safety story and it is now genuinely closed.
- ⭐ **Circuit Breaker** ✅ — downstream assets tagged `Sentinel-Degraded` in
  DataHub and the scoring job paused via a breaker `ml/score.py` honours; both
  auto-restored on resolution. Airflow/Dagster pausing is still ⬜.
- **Quarantine / backfill** 🔨 — bad rows are isolated into a `sentinel_quarantine`
  table named for the incident; triggering a corrected backfill is still ⬜.
- **Real multi-file / multi-repo PRs** 🔨 — CodeFixTool now takes a generic
  `(file, instruction)` request rather than only understanding vendor advisories,
  so any incident class can earn a code fix — a label leak produces a diff
  removing the leaking feature from `ml/config.py`. Still single-file; multi-file
  migrations, running the test suite on the fix, and org-wide scanning remain ⬜.
- **Fix verification** 🔨 — a generated fix is parsed before it is proposed, and a
  rollback target is scored before promotion. Running the full test suite on a
  proposed fix is still ⬜.

## 2. Detection — more signal sources (Detector plugins)
- ⭐ **Model-drift detector** ✅ — prediction-distribution shift from the scoring loop,
  sharing `ml/drift.py` with the scoring job so the two cannot disagree.
- ⭐ **Freshness / SLA detector** ✅ — lag measured against the recorded healthy
  baseline rather than wall-clock.
- **Volume-anomaly detector** ✅ — row counts vs baseline, catching both a thin
  delivery and a re-delivered batch.
- **Label-leakage detector** ✅ — a champion scoring *above* a ceiling, with the
  leaking feature named by correlation dominance.
- **Training/serving-skew detector** ✅ — serving feature means vs the champion's
  logged training distribution.
- **Git-commit detector** ✅ — a commit to a pipeline source is a signal,
  attributed to its author/sha and mapped to the impacted asset; contained +
  owner paged (a human commit is flagged, not auto-reverted).
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
- **Git-blame probe** ✅ — the exact commit + author behind a change; the RCA
  narrative now names it.
- **Training/serving-skew probe** ✅ — feature distributions at train vs serve time.
- **Cross-incident correlation** 🔨 — basic same-root dedupe exists; add semantic
  clustering of simultaneous incidents to one root cause.
- **LLM-pipeline probes** ⬜ — prompt-template diff, tokenizer/config change, eval-set
  regression, dataset contamination, RAG retrieval-quality checks.

## 4. Memory & knowledge (the compounding moat)
- **Vector memory** ⬜ — embeddings for semantic recall of similar past incidents
  (today: same-asset + same-change-type filter).
- **Runbook → DataHub Skill** ✅ — synthesised from repeated post-mortems and
  registered as a DataHub `AgentSkill` entity.
- **CodebaseMemory → DataHub** ⬜ — ingest code files as assets so code↔data lineage
  lives in the graph, not just in-process.
- **MTTR / learning analytics** ⬜ — track resolution time trending down as memory grows.

## 5. Autonomy, policy & governance
- **Tiered autonomy** ✅ — tags, RCA confidence and blast radius decide the tier,
  and the tier genuinely gates what runs: protective actions at every tier,
  mutating actions withheld under `HUMAN_ONLY`.
- ⭐ **Shadow mode + savings digest** ✅ — `python -m agent --shadow` plans and
  records without applying; `python -m agent digest` reports what it would have done.
- **Human-in-the-loop approvals** ⬜ — approve/deny an action from Slack.
- **Audit log** ✅ — `ActionJournal` writes every action + its inverse to
  `.sentinel/journal.jsonl`, append-only and replayable (Phase 0).

## 6. Product surface (what users actually touch)
- ⭐ **Slack/Teams integration** ✅ — incident channel, audience-aware messages (`agent/reporting/comms.py`), interactive Socket Mode approvals.
- ⭐ **Web dashboard** ✅ — Next.js live command center with Overview, Incidents, Pipeline Observability, Trends, Asset Health, API Health (Self-Maintaining APIs), Runbooks, and Activity audit trail.
- **Pipeline Observability** ✅ — stage-by-stage traces, execution times, real-time log streaming with level filters, and throughput/latency/error-rate sparklines.
- **Self-Maintaining APIs Dashboard** ✅ — dedicated `/api-health` interface with active breaking-change advisories, full codebase dependency inventory, lineage blast-radius graph, multi-file diff modal, and SRE scan/webhook triggers.
- **Cost-of-incident meter** ✅ — dollar impact from the real blast radius × team-owned rates in `config/cost_model.yaml`, written into the asset's catalog "About" box; cites its assumptions.
- **Trust badges / health scores** ✅ — a 0-100 score and A–D grade written onto each asset, refreshed whenever an incident closes.
- **Ask-the-on-call** ✅ — grounded LLM chat over incident memory with full Markdown rendering, code snippets, lists, blockquotes, and interactive clickable incident badge citations (`INC-xxxx`).
- **Paging** ✅ — PagerDuty routing for human-tier incidents (`shared_pagerduty`).

## 7. Platform & enterprise readiness
- **Multi-warehouse** ⬜ — Snowflake / BigQuery / Databricks / Redshift (today: DuckDB).
- **Scale** ⬜ — async job queue, many concurrent incidents, rate-limited LLM calls.
- **Multi-tenancy / RBAC / auth** ⬜.
- **Deployment** ⬜ — containerized service, scheduled runs, webhook triggers.
- **Connectors** ⬜ — dbt Cloud, Fivetran, Airflow, GitHub App install.

## 8. The self-maintaining-API wedge (YC framing)
The dependency/API vertical is the sharpest standalone product ("Dependabot for APIs").
- **Vendor webhook ingestion** ✅ — `POST /api/v1/advisory` webhook endpoint for vendors and registries to push breaking-change advisories.
- **Multi-file auto-migration** ✅ — AST scan + LLM rewrite across all affected call-sites + shadow verification + PR generation.
- **Lineage blast radius** ✅ — traces external API releases across DataHub model and scoring deployment DAGs.
- **SRE & on-call integration** ✅ — on-demand scan triggers, circuit breakers, trust score degradation, and dashboard visualization.
- **Vendor changelog tracking** ⬜ — monitor SDK releases / OpenAPI diffs to derive breaking changes automatically.
- **Per-provider agents** ⬜ — "install Stripe's update agent."
- **Neutral third-party service** ⬜ — track changes across many vendors, scan customer repos, open PRs.
- **Org-wide repo scanning** ⬜ — one advisory → PRs across every affected repo.

## Suggested build order (post-hackathon → product)
1. ⭐ Time Machine + validation gate + auto-rollback (real actuation, the trust core).
2. ⭐ Circuit Breaker + Slack integration (visible remediation + product surface).
3. ⭐ Model-drift + freshness detectors (coverage of the most common silent failures).
4. Shadow mode + savings digest + dashboard (enterprise adoption on-ramp).
5. Vector memory + runbook→Skill (the compounding moat + OSS contribution).
6. Multi-warehouse + deployment + connectors (make it installable).
