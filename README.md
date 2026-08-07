# Sentinel

Autonomous incident-remediation agent for data & ML pipelines, built on DataHub.

Sentinel detects incidents, root-causes them over the real DataHub context graph
(lineage, schema, ownership, tags) with grounded evidence, computes blast radius
across the `raw → feature → model → deployment` chain, proposes a remediation, and
writes a post-mortem back so the graph gets smarter each time.

**Incident classes it handles today**

- **Data** — failed dbt assertions + data profiling (null spike, scale shift,
  distribution drift, schema change).
- **Dependency / API breaking change** — a vendor advisory triggers a codebase
  scan and an LLM-generated migration PR ("self-maintaining APIs").
- **ML training regression** — a champion model whose eval metrics dropped.

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
historical mean) at high confidence. Try `null_spike`, `distribution_drift`
(subtle — no hard violation), and `schema_change` the same way.

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

### ML training regression

```bash
python -m scenarios training_regression   # ships a deliberately weak champion
python -m agent
python -m scenarios reset                  # restores the champion automatically
```

Expect: the agent reads the champion's MLflow metrics, flags the `roc_auc`
regression below threshold, and root-causes it.

The bad model version is deliberately **not** tagged `validation_status=passed`,
which is how the rollback tells a version worth returning to from one that
shipped broken. `reset` re-points the `champion` alias at the newest validated
version, so `python -m ml.train` is no longer needed to recover.

### Notes

- **No LLM key?** The agent still runs — RCA uses a deterministic, evidence-based
  fallback instead of the LLM narrative.
- **Offline smoke test:** `python -m agent --fake` runs the full loop on canned
  data with no DataHub or LLM key.
- **What's real vs stubbed:** detection, context, RCA, memory, and fix generation
  are real. The mitigation actuators (`act`/`undo` rollback, circuit breaker,
  post-mortem write-back) are still stubs, so today's run reports a mitigation it
  did not actually perform — the machinery they need (snapshots, action journal,
  dbt test parsing, model registry reads) is in place as of Phase 0 and is wired
  up in Phase 1. See `TASK_DISTRIBUTION.md`.

---

## Working state on disk

Two directories hold the agent's own state. Both are gitignored and both are safe
to delete — you lose the rollback history, not the pipeline.

| Path | What it is |
|---|---|
| `.sentinel/baselines.json` | the pipeline's healthy shape; how silent failures (stale feed, volume collapse) are detected at all |
| `.sentinel/advisories/*.json` | published vendor advisories awaiting the dependency detector |
| `.sentinel/journal.jsonl` | every action taken and the inverse that undoes it (audit log + rollback source) |
| `sentinel_snap` schema in `fraud.duckdb` | point-in-time table copies the Time Machine restores from |

Inspect them any time:

```bash
cat .sentinel/baselines.json
python -c "from agent.tools.warehouse.snapshots import SnapshotStore as S; print(S().labelled_tables('last_good'))"
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
