# Sentinel

Autonomous incident-remediation agent for data & ML pipelines, built on DataHub.

Sentinel detects incidents, root-causes them over the real DataHub context graph
(lineage, schema, ownership, tags) with grounded evidence, computes blast radius
across the `raw → feature → model → deployment` chain, proposes a remediation, and
writes a post-mortem back so the graph gets smarter each time.

**Incident classes it handles today**

- **Data quality** — failed dbt assertions + profiling: null spike, scale shift,
  distribution drift, schema change, duplicate batch.
- **Silent data failures** — the ones every assertion passes: a feed that stopped
  delivering, a batch that arrived at a fraction of its size.
- **Silent model failures** — prediction drift, training/serving skew, and label
  leakage (a model that got *suspiciously good* because the target leaked into a
  feature).
- **Dependency / API breaking change** — a vendor advisory triggers a codebase
  scan and an LLM-generated migration PR ("self-maintaining APIs").
- **ML training regression** — a champion model whose eval metrics dropped.

Half of those leave **all 22 dbt assertions green**. A pipeline can be badly
wrong while every test it has says otherwise, which is why detection here does
not rely on assertions alone.

**How the RCA pipeline works**

```
detect            read context        investigate            recall            synthesize          remediate + learn
(Detectors)  ->   (DataHub graph) ->  (Probes: profiling, -> (Memory: prior -> (structured RCA  ->  (fix / rollback +
                                       lineage, codebase)     incidents)        over evidence)       post-mortem to graph)
```

New incident types are added as plugins; the core doesn't change. There are four
extension surfaces, all registered by a decorator:

| Surface | Answers | Registered with |
|---|---|---|
| `Detector` | how do we notice? | `@detector` |
| `Probe` | what grounded evidence explains it? | `@probe` |
| `Actuator` | how do we fix it, reversibly? | `@actuator` |
| `CheckRunner` | how do we prove the fix worked? | `@check` |

See `TASK_DISTRIBUTION.md` for the phase plan and product roadmap.

---

## Prerequisites

- Python 3.11
- Docker Desktop (running)
- Git
- ~8 GB free RAM for the DataHub quickstart containers

## Setup

### 1. Clone and install

```bash
git clone <your-repo-url> sentinel
cd sentinel

python -m venv .venv
.venv\Scripts\activate            # Windows
source .venv/bin/activate         # macOS/Linux

pip install -r requirements.txt
```

### 2. Configure the LLM (recommended)

RCA uses an LLM via [OpenRouter](https://openrouter.ai) (OpenAI-compatible).
Without a key the agent still runs, using a deterministic RCA fallback.

```bash
cp .env.example .env
# then set in .env:
#   OPENROUTER_API_KEY=sk-or-...
#   OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free   # any OpenRouter model
```

`.env` is gitignored — never commit your key.

### 3. Start DataHub

```bash
datahub docker quickstart
```

On Windows the CLI may error on a unicode character at the very end — the stack
still started. Set `PYTHONIOENCODING=utf-8` to silence it (`set` on Windows,
`export` on macOS/Linux). Then confirm the UI at http://localhost:9002
(login `datahub` / `datahub`); it's empty until ingestion.

### 4. Build the data pipeline

```bash
python pipeline/generate_raw_data.py     # synthetic transaction seed

cd pipeline/dbt
dbt seed          --profiles-dir .
dbt run           --profiles-dir .
dbt docs generate --profiles-dir .        # manifest + catalog
dbt build         --profiles-dir .        # run + test -> assertions
cd ../..
```

All 22 dbt tests should pass on clean data.

### 5. Train the model

```bash
python -m ml.train   # trains + registers fraud_detection_model @champion in MLflow
python -m ml.score   # scores current features, saves the drift baseline
```

### 6. Ingest into DataHub

```bash
python -m ingestion
```

Runs both ingestion recipes (dbt + MLflow), wires the ML lineage, and applies
governance (tags + owners). Resolves all paths from the repo root, so it works
from any directory.

### 7. Verify

Open http://localhost:9002 and search `fraud`. You should see 10 datasets with
table- and column-level lineage, 22 assertions, and `fraud_detection_model` with
a training job, metrics, and a scoring deployment. Open the model's **Lineage**
tab for the full `raw_transactions → features → training_dataset → model →
deployment` chain.

---

## Running the RCA pipeline

Every incident is a three-step loop: **inject a scenario → run the agent →
reset**. `python -m agent` runs the full pipeline (detect → context →
investigate → recall → RCA → remediate → post-mortem) against live DataHub.

List scenarios any time. Scenarios marked `[silent: dbt stays green]` break the
pipeline *without* tripping a single assertion — the failures a test suite can't
see:

```bash
python -m scenarios list
```

### Capture the "last known good" state first

Before injecting anything, give the agent something to roll back to:

```bash
python -m scenarios snapshot
```

This copies every base table into a `sentinel_snap` schema inside
`pipeline/dbt/fraud.duckdb` and records the pipeline's healthy shape (row counts,
newest timestamps) to `.sentinel/baselines.json`. `python -m scenarios reset`
does it automatically whenever the assertions come back green — it deliberately
skips the capture when they don't, so a broken state can never become the thing
rollbacks restore to.

### Data incident (assertion + profiling)

```bash
python -m scenarios unit_bug     # amounts reported in cents (100x scale shift)
python -m agent
python -m scenarios reset
```

Expect: the agent detects the failed assertion, profiles upstream tables, and
pins `raw_transactions.amount` as a `scale_shift` with real numbers (recent vs
historical mean) at high confidence — then **quarantines the offending rows,
restores the table from the last-good snapshot, tags the downstream assets, and
re-runs the assertions to confirm it worked.** Try `null_spike`,
`distribution_drift` (subtle — no hard violation), and `schema_change` the same
way.

What counts as an "offending row" comes from the last-good snapshot, not from any
knowledge of how the data was broken: a value outside the range ever seen while
the pipeline was healthy is one the pipeline was never built to handle.

### Dependency / API breaking change ("self-maintaining APIs")

```bash
python -m scenarios api_breaking_change   # publishes a vendor advisory
python -m agent
python -m scenarios reset
```

Expect: the agent detects the advisory, scans the **codebase** for affected
usages, traces them to the impacted DataHub model, and writes a real migration
diff to `examples/generated_fixes/<incident>.diff`. Set `GITHUB_TOKEN` and
`GITHUB_REPO` in `.env` to open an actual draft PR instead.

### Silent failures — the ones dbt cannot see

These leave **all 22 assertions passing**. Check for yourself between the inject
and the agent run:

```bash
python -m scenarios stale_feed          # the feed stopped delivering
python -c "from agent.tools.warehouse.dbt_runner import DbtRunner as D; print('dbt green:', D().test().ok)"
python -m agent                          # detects anyway, and CONTAINS
python -m scenarios reset
```

Expect `stale_feed` to be **contained**, not resolved: the missing rows cannot be
conjured, so the agent flags every downstream asset, opens the scoring breaker,
pages the owner, and leaves the protection up. Confirm it held:

```bash
cat .sentinel/breakers/fraud_scoring_api.json
python -m ml.score                       # refuses to run
```

The others follow the same three-step loop:

| Scenario | What breaks | Outcome |
|---|---|---|
| `volume_collapse` | 60% of rows never arrive | **repaired** — pinned back from the last-good snapshot |
| `model_drift` | a uniform repricing shifts predictions | **repaired** — champion repointed |
| `training_serving_skew` | serving features drift from the training distribution | **contained** — only retraining truly fixes it |
| `label_leakage` | a label-derived surcharge leaks into `amount`; `roc_auc` hits 0.998 | **repaired** + a diff removing the feature |
| `duplicate_batch` | a batch is delivered twice | **repaired** — deduplicated |

`label_leakage` is the one worth watching. A detector that only checks for
metrics *falling* would wave it through and ship the model:

```bash
python -m scenarios label_leakage && python -m agent
cat examples/generated_fixes/LEAK-*.diff      # removes `amount` from FEATURES
python -m scenarios reset
```

### ML training regression

```bash
python -m scenarios training_regression   # ships a deliberately weak champion
python -m agent
python -m scenarios reset                  # restores the champion automatically
```

Expect: the agent reads the champion's MLflow metrics, flags the `roc_auc`
regression below threshold, root-causes it, and **moves the `champion` alias back
to the last validated version.** Confirm with:

```bash
python -c "from agent.tools.warehouse.champion import ChampionMetrics as C; v=C().current(); print('champion v'+v.version, round(v.roc_auc,4))"
```

The bad model version is deliberately **not** tagged `validation_status=passed`,
which is how the rollback tells a version worth returning to from one that
shipped broken. `reset` re-points the `champion` alias at the newest validated
version, so `python -m ml.train` is no longer needed to recover.

### Notes

- **No LLM key?** The agent still runs — RCA uses a deterministic, evidence-based
  fallback instead of the LLM narrative.
- **Offline smoke test:** `python -m agent --fake` runs the full loop on canned
  data with no DataHub or LLM key.
- **What's real:** all of it. Detection, context, RCA, memory, fix generation and
  the mitigations — the agent moves rows, restores tables, repoints the MLflow
  champion, tags assets and opens circuit breakers, every action journaled with a
  working inverse. See `TASK_DISTRIBUTION.md` for what is deliberately out of
  scope.

---

## Other things it does

```bash
python -m agent drill <scenario>   # break it on purpose, then watch it heal
python -m agent --shadow           # decide what to do, record it, change nothing
python -m agent digest             # what it did, or would have done
python -m agent badges             # health grade on every asset
python -m agent runbooks           # write runbooks from what it has learned
```

**Fire drill.** An agent nobody has seen fail is an agent nobody should trust, so
this is re-runnable on demand rather than demonstrated once: inject a real
failure, detect it, root-cause it, fix it, verify. The pass condition is the
scenario's own declared expectation, so a drill checks the agent noticed *the
right thing* rather than merely noticing something.

**Shadow mode** is the on-ramp. The agent reasons all the way to a plan and
records it, applies nothing, and leaves the incident open — then `digest` tells
you what it would have done. Run it for a week before you let it act.

**Trust badges** put a 0-100 score and an A–D grade on each asset in DataHub,
computed from failing assertions, open incidents, and deviation from the recorded
baseline. The inputs are published next to the score, because a health grade
nobody can explain is one nobody will act on. The grade refreshes whenever an
incident closes — including a *contained* one, which is when a low grade matters
most. The score and its arithmetic are written into the asset's editable
description (the catalog "About" box), so a human browsing the table sees the same
health the agent does.

**Incident cost.** Each resolved incident carries an estimated business exposure,
shown in the badge and the agent log. Sentinel does not invent the figure: it
measures the real downstream blast radius from the lineage graph and applies the
rates in **`config/cost_model.yaml`** — which are *yours* to set (per-consumer
rates, assumed MTTR, per-change-type severity). Every estimate cites its
assumptions, flags when it fell back to illustrative defaults, and produces no
dollar figure at all when you set `enabled: false`. The number is only ever as
good as your config, so it always shows its work.

**Runbooks.** Every resolved incident leaves a post-mortem. Once there are
several of the same kind, `runbooks` reads them back and writes down the
procedure already implicit in them, registering it as a DataHub **`AgentSkill`** —
discoverable by the next person *and* the next agent, beside the assets it
applies to.

**Root cause names the commit.** The codebase index already maps each source file
to the asset it produces. Read backwards, that turns "`raw_transactions.amount`
shifted 100x" into "commit `b6a87ca` by SRINJOY59 changed the ingestion" — which
is what someone actually needs in order to fix it.

**Nothing is promoted untested.** A rollback target is scored against today's
data before the champion alias moves, and a generated code fix is parsed before
it is proposed. Neither touches production; both produce a before/after you can
put in a PR.

**Reads DataHub through the MCP Server.** Set `SENTINEL_USE_MCP=1` and Sentinel
reads lineage and schema through the official
[DataHub MCP Server](https://docs.datahub.com/docs/features/feature-guides/mcp) —
the same `mcp-server-datahub` that Claude Desktop and Cursor use — instead of the
Python SDK. The server runs isolated via `uvx mcp-server-datahub@latest` (needs
[`uv`](https://docs.astral.sh/uv/)) against the local Core instance; if it can't
start, Sentinel falls back to the SDK, so the flag is always safe to leave on.

---

## What the agent actually does to your system

Every mitigation is real and every one of them is reversible. When the agent
acts, it writes what it did *and how to undo it* to `.sentinel/journal.jsonl`
before the action takes effect, so a rollback never depends on the agent still
being alive.

| Action | What changes on disk / in DataHub |
|---|---|
| `quarantine` | rows outside the healthy range move to `sentinel_quarantine.<table>__<incident>` |
| `pin_feature` | the table is restored from the `last_good` snapshot, then dbt rebuilds downstream |
| `dedupe_partition` | duplicate keys are dropped, first arrival kept |
| `repoint_model` | the MLflow `champion` alias moves to the newest **validated** healthy version |
| `tag_asset` | downstream assets get `Sentinel-Degraded` in DataHub |
| `pause_job` | a breaker opens and **`python -m ml.score` refuses to run** |

Then the validation gate runs — dbt assertions, model metrics, the model's input
distributions, and the volume / freshness invariants. Nothing is reported as
resolved that a check did not independently confirm.

### Repaired, contained, or rolled back

Not every incident can be fixed, and pretending otherwise is worse than saying so.

| Gate result | What the agent does |
|---|---|
| **green** | resolved. Protection is lifted automatically — breaker closed, downstream flags cleared — and the post-mortem written to the graph. |
| **red, after a repair attempt** | the data actions are withdrawn through the journal, but **the protective ones stay**: the pipeline is still bad, so the warning stands. Owners are paged. |
| **red, and no repair was possible** | **contained.** Data that never arrived cannot be restored from a snapshot. The tags and breaker hold, the incident stays open with `Sentinel-Degraded` in place, `Sentinel-Resolved` is withheld, and a post-mortem is recorded as *contained, awaiting human* — so memory learns from the incidents the agent cannot fix too. |

### How much it is allowed to do on its own

Actions split by what they touch. *Protective* ones (tag, pause) only reduce
harm, so they run at every tier — withholding them while waiting for a human is
itself the risky choice. *Mutating* ones (pin, quarantine, dedupe, repoint)
change data or what is serving.

| Tier | Trigger | Behaviour |
|---|---|---|
| `auto` | no sensitive tags, high confidence, small blast radius | acts, no PR needed |
| `pr_only` | `Tier-Critical` / `PII` / low confidence / wide blast radius | mitigates now, opens a fix for review |
---

## Web Dashboard & Pipeline Observability

The Next.js dashboard provides a live command center for data engineers and on-call operators:

```bash
# In terminal 1: Start the Sentinel backend & webhook server (port 8090)
python -m agent serve

# In terminal 2: Start the Next.js UI (port 3000)
cd web
npm install
npm run dev
```

Visit **http://localhost:3000** to explore:
- **Overview (`/`)**: Live MTTR, resolved vs. open incidents, exposure avoided, and autonomy breakdown.
- **Incidents (`/incidents`)**: Searchable, filterable list with full root-cause narratives, action timelines, cost breakdowns, and draft PR links.
- **Pipeline (`/pipeline`)**: Stage-by-stage execution traces, real-time log streaming with level filters (INFO/WARN/ERROR/DEBUG), records/hr throughput, p95 latency, and error rate sparklines.
- **Trends (`/trends`)**: 7/30/90-day time-series of incident frequencies, exposure amounts, and MTTR curves.
- **Asset Health (`/assets`)**: Trust scores (0–100) and reliability grades (A–D) computed from assertion failures, drift, freshness lag, and past incidents.
- **Runbooks (`/runbooks`)**: Autonomous `AgentSkill` runbooks synthesized from resolved incident post-mortems and registered in DataHub.
- **Activity (`/activity`)**: Append-only action journal, manual fire drill trigger, and one-click rollback.
- **Ask On-Call (`/chat`)**: Incident-grounded assistant with full Markdown rendering, code snippets, lists, blockquotes, and interactive clickable incident badge citations (`INC-xxxx`).

### Populating Demo / Seed Data

To populate the dashboard with realistic incidents, traces, and journal entries across all 14 change types and 12 production datasets:

```bash
python scripts/seed_incidents.py
```

This writes directly to `.sentinel/incidents.db` (SQLite) and `.sentinel/journal.jsonl`, generating 35+ realistic incidents with root causes, costs ($500–$25K), narratives, and action timelines.

---

## Working state on disk

Two directories hold the agent's own state. Both are gitignored and both are safe
to delete — you lose the rollback history, not the pipeline.

| Path | What it is |
|---|---|
| `.sentinel/baselines.json` | the pipeline's healthy shape; how silent failures (stale feed, volume collapse) are detected at all |
| `.sentinel/advisories/*.json` | published vendor advisories awaiting the dependency detector |
| `.sentinel/journal.jsonl` | every action taken (or, in shadow mode, simulated) and the inverse that undoes it — audit log, rollback source, and digest input |
| `.sentinel/breakers/*.json` | open circuit breakers; `ml/score.py` refuses to run while one exists |
| `sentinel_snap` schema in `fraud.duckdb` | point-in-time table copies the Time Machine restores from |
| `sentinel_quarantine` schema in `fraud.duckdb` | rows isolated from a bad batch, kept per incident for inspection |

Inspect them any time:

```bash
cat .sentinel/journal.jsonl        # what the agent did, and how to undo it
cat .sentinel/baselines.json
python -c "from agent.tools.warehouse.snapshots import SnapshotStore as S; print(S().labelled_tables('last_good'))"
```

Roll an incident back by hand — the same path the failed-validation branch takes:

```bash
python -c "from agent.tools.mechanisms.composite import RealMechanisms; print(RealMechanisms().rollback('INC-1234'))"
```

---

## Verifying the foundation

These need no Docker, no DataHub and no API key — run them first when something
looks wrong, to tell "the agent is broken" apart from "the environment is":

```bash
python -m agent --fake                  # full loop on canned data
python -c "import compileall,sys; sys.exit(0 if compileall.compile_dir('agent',quiet=1) else 1)"
```

With the warehouse built, these exercise the pieces the remediation loop is built
on. The last one is the important one — it proves a poisoned pipeline can be
restored exactly:

```bash
# the validation gate: which assertions pass, by name
python -c "from agent.tools.warehouse.dbt_runner import DbtRunner as D; r=D().test(); print(r.ok, len(r.passed), r.failed)"

# the model registry: current champion, and what a rollback would target
python -c "from agent.tools.warehouse.champion import ChampionMetrics as C; c=C(); v=c.current(); print(v.version, v.roc_auc, v.validated); print('rollback ->', c.last_good(exclude_version=v.version))"

# the Time Machine: break it, restore it, prove the restore was exact
python -c "from agent.tools.warehouse.snapshots import SnapshotStore as S; s=S(); print('before', s.fingerprint('raw_transactions'))"
python -m scenarios unit_bug --no-reingest
python -c "from agent.tools.warehouse.snapshots import SnapshotStore as S; s=S(); s.restore('raw_transactions','last_good'); print('after ', s.fingerprint('raw_transactions'))"
python -c "from agent.tools.warehouse.dbt_runner import DbtRunner as D; d=D(); d.run(quiet=True); print(d.test().ok)"
```

The two fingerprints must match, and the final line must print `True`.

## Proving the mitigations are real

The point of the loop is that it changes things and can change them back. This
sequence proves both, and is the honest test of whether the agent works:

```bash
python -m scenarios reset                 # clean, and capture last-good
python -c "from agent.tools.warehouse.snapshots import SnapshotStore as S; print('poison-free:', S().fingerprint('raw_transactions'))"

python -m scenarios unit_bug              # break it
python -c "from agent.tools.warehouse.snapshots import SnapshotStore as S; print('poisoned  :', S().fingerprint('raw_transactions'))"

python -m agent                           # detect -> RCA -> quarantine + pin + tag -> validate
cat .sentinel/journal.jsonl                # every action, with its inverse

# now undo everything the agent did, and confirm the break comes back
python -c "from agent.tools.mechanisms.composite import RealMechanisms as R; from agent.journal import ActionJournal as J; inc=J().entries()[0].incident_id; print(R().rollback(inc))"
python -c "from agent.tools.warehouse.snapshots import SnapshotStore as S; print('rolled back:', S().fingerprint('raw_transactions'))"
python -c "from agent.tools.warehouse.dbt_runner import DbtRunner as D; d=D(); d.run(quiet=True); print('assertions:', d.test().ok)"
```

The `rolled back` fingerprint must equal the `poisoned` one, and the assertions
must print `False` — the pipeline is broken again, which is what proves the fix
had been real rather than reported.

And that a *silent* failure is caught with dbt fully green, then contained rather
than falsely resolved:

```bash
python -m scenarios reset
python -m scenarios stale_feed
python -c "from agent.tools.warehouse.dbt_runner import DbtRunner as D; print('dbt green:', D().test().ok)"   # True
python -m agent                                        # must say CONTAINED
python -m ml.score                                     # must refuse: breaker open
python -m scenarios reset
```

The whole loop in one command, repeatable any time:

```bash
python -m agent drill unit_bug        # inject -> detect -> RCA -> fix -> verify
python -m agent digest                # what it just did, in hours
python -m scenarios reset
```

Shadow mode must change nothing — check that it doesn't:

```bash
python -m scenarios null_spike
python -m agent --shadow
python -c "from agent.tools.warehouse.dbt_runner import DbtRunner as D; print('still broken:', not D().test().ok)"
ls .sentinel/breakers/ 2>/dev/null || echo "no breakers opened - correct"
python -m scenarios reset
```

Check the circuit breaker independently:

```bash
python -m scenarios training_regression && python -m agent    # champion v2 -> v1
python -c "from agent.tools.warehouse.champion import ChampionMetrics as C; v=C().current(); print('champion v'+v.version, v.roc_auc)"
python -m ml.score                        # runs; add a breaker and it refuses
```

---

## Reset / teardown

```bash
python -m scenarios reset   # restore a clean, healthy pipeline
```

`reset` asks every scenario to clean up after itself (clearing advisories,
re-pointing the MLflow `champion` alias at the newest validated version), then
re-seeds, rebuilds, re-runs the assertions, re-captures the last-good snapshot,
and refreshes DataHub. Add `--no-reingest` to skip the DataHub refresh for faster
local iteration.

```bash
datahub docker nuke         # remove all DataHub containers + volumes
datahub docker quickstart   # fresh start (then re-run setup steps 4–6)
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
