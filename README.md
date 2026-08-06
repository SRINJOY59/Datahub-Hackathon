# Sentinel

Autonomous ML-incident remediation agent built on DataHub. Sentinel detects data
incidents from DataHub assertions, reads the real lineage/schema/ownership/tags
to root-cause them (LLM over the context graph), computes blast radius across the
`raw → feature → model → deployment` chain, and runs a remediation loop.

This README covers setup for the current state: the fraud ML pipeline, the model,
end-to-end lineage ingestion, incident scenarios, and the agent.

## Prerequisites

- Python 3.11
- Docker Desktop (running)
- Git
- ~8 GB free RAM for the DataHub quickstart containers

## 1. Clone and install

```bash
git clone <your-repo-url> sentinel
cd sentinel

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

## 2. Start DataHub

```bash
datahub docker quickstart
```

On Windows, if the CLI errors on a unicode character at the very end, the stack
still started — set `PYTHONIOENCODING=utf-8` to silence it:

```bash
set PYTHONIOENCODING=utf-8   # Windows
export PYTHONIOENCODING=utf-8 # macOS/Linux
```

Wait until the containers are healthy, then confirm the UI is up at
http://localhost:9002 (login `datahub` / `datahub`). It will be empty until
ingestion (step 5).

## 3. Build the data pipeline

```bash
# generate the synthetic transaction seed
python pipeline/generate_raw_data.py

cd pipeline/dbt
dbt seed          --profiles-dir .
dbt run           --profiles-dir .
dbt docs generate --profiles-dir .   # produces manifest + catalog
dbt build         --profiles-dir .   # run + test -> run_results (assertions)
cd ../..
```

All 21 dbt tests should pass on the clean data.

## 4. Train the model

```bash
python -m ml.train   # trains + registers fraud_detection_model @champion in MLflow
python -m ml.score   # scores current features, saves the drift baseline
```

## 5. Ingest into DataHub

```bash
python -m ingestion
```

This runs both ingestion recipes (dbt + MLflow), wires the ML lineage, and
applies governance (tags + owners). It resolves all paths from the repo root,
so it works from any directory.

## 6. Verify

Open http://localhost:9002 and search `fraud`. You should see:

- 10 datasets (5 dbt models + 5 sibling DuckDB tables) with table- and
  column-level lineage
- 21 assertions (the dbt tests) on the datasets
- `fraud_detection_model` with a training job, training metrics, and a scoring
  deployment — open its **Lineage** tab to see the full
  `raw_transactions → features → training_dataset → model → deployment` chain

## Incident scenarios

Inject a silent incident (poisons a feature, trips an assertion, drifts the
model, and surfaces in DataHub), or restore a clean state:

```bash
python -m scenarios list        # available scenarios
python -m scenarios unit_bug    # inject the cents/dollars unit bug
python -m scenarios null_spike  # inject a null-spike
python -m scenarios reset        # restore a clean, healthy pipeline
```

## Configure the agent LLM (optional)

The agent uses an LLM for root-cause analysis via [OpenRouter](https://openrouter.ai)
(OpenAI-compatible). Without a key it still runs, using a deterministic RCA
fallback.

```bash
cp .env.example .env
# then set in .env:
#   OPENROUTER_API_KEY=sk-or-...
#   OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free   # any OpenRouter model
```

`.env` is gitignored — never commit your key.

## Run the agent

End-to-end demo flow (break → detect → root-cause → restore):

```bash
python -m scenarios unit_bug   # inject a silent incident, refresh DataHub
python -m agent                # detect from DataHub, read real context, LLM RCA, remediate
python -m scenarios reset       # restore a clean, healthy pipeline
```

`python -m agent` reads open incidents and lineage live from DataHub. Detection
and context are backed by DataHub; the mitigation tools (rollback, circuit
breaker, fix-PR, post-mortem write-back) are being built and currently run as
stubs. Use `python -m agent --fake` for a fully offline smoke test (no DataHub or
LLM key needed).

## Resetting DataHub

```bash
datahub docker nuke        # removes all DataHub containers + volumes
datahub docker quickstart  # fresh start (then re-run steps 3-5)
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
