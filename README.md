# Sentinel

Autonomous ML-incident remediation agent built on DataHub. This README covers
setup for the current state: the fraud ML pipeline, the model, and ingestion of
the end-to-end lineage into DataHub.

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

## Run the agent

```bash
python -m agent   # runs the remediation loop (fake tools until real ones land)
```

## Resetting DataHub

```bash
datahub docker nuke        # removes all DataHub containers + volumes
datahub docker quickstart  # fresh start (then re-run steps 3-5)
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
