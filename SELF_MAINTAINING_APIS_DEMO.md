# Self-Maintaining APIs — Production Architecture & Demo Guide

Sentinel implements **Self-Maintaining APIs** using a dual architecture:
1. **Push-Based Webhooks**: For Vendor SaaS APIs (Stripe, Twilio), GitHub Releases, and Data Pipeline orchestrators (dbt, Airflow).
2. **Upstream Registry Monitoring**: For open-source package registries (PyPI, npm) using automated SemVer analysis (Dependabot/Renovate pattern).

---

## Architecture Overview

```
                      ┌────────────────────────────────────────┐
                      │            SENTINEL AGENT              │
                      └──────────────────┬─────────────────────┘
                                         │
        ┌────────────────────────────────┴────────────────────────────────┐
        ▼                                                                 ▼
 📡 TRUE WEBHOOKS (Push / Event-Driven)                ⏰ REGISTRY MONITOR (Poll / Scheduled)
 ──────────────────────────────────────                ───────────────────────────────────────
 • POST /webhook/github (GitHub Releases / PRs)        • Queries PyPI JSON API for packages
 • POST /webhook/advisory (Stripe, Twilio SaaS APIs)   • Compares installed vs. latest SemVer
 • POST /webhook/dbt (dbt Cloud run failures)          • Generates breaking-change advisories
 • POST /webhook/airflow (DAG failure alerts)          • Triggered via CLI (python -m agent sync)
                                                         or REST (/api/v1/advisories/sync-registry)
```

---

## 5 Production Demo Scenarios

### Scenario 1: The ML Champion Model API Break (`scikit-learn 2.0`)
> **The Story:** A vendor releases a breaking change in an ML library that our fraud-detection training pipeline imports.

#### How to Test:
```bash
# 1. Inject the breaking change advisory
.\.venv\Scripts\python.exe -m scenarios api_breaking_change

# 2. Run the autonomous Sentinel agent
.\.venv\Scripts\python.exe -m agent
```

#### What Happens:
1. **Terminal**: Sentinel catches `DEP-scikit-l`, maps call-sites in `ml/train.py`, traces the DataHub blast radius to `fraud_detection_model_1` $\to$ `fraud_scoring_api`, and generates a validated diff.
2. **Dashboard (`http://localhost:3000/api-health`)**:
   - **Active Advisories Tab**: Shows scikit-learn advisory with highlighted call-site `ml/train.py:42`.
   - **Lineage Blast Radius Tab**: Displays the 4-step DAG showing that breaking `scikit-learn` puts our live fraud-scoring API at risk ($3,000 exposure avoided).
   - **Migration History Tab**: Click **"View Generated Diff"** to inspect the LLM-generated code fix.

---

### Scenario 2: Live Vendor Webhook Ingestion (`stripe v10.0`)
> **The Story:** Stripe sends a live developer webhook announcing that `stripe.Charge.create()` is deprecated in favor of `stripe.PaymentIntent.create()`.

#### How to Test (Live from the UI):
1. Navigate to **`http://localhost:3000/api-health`**.
2. Click **"Ingest Vendor Webhook"** in the top right.
3. Fill in the modal (or use the REST endpoint via `curl`):
   ```json
   {
     "package": "stripe",
     "from_version": "9.5.0",
     "to_version": "10.0.0",
     "summary": "stripe.Charge.create() deprecated in favor of stripe.PaymentIntent.create()",
     "migration": "Replace stripe.Charge.create(amount=x) with stripe.PaymentIntent.create(amount=x, currency='usd')",
     "symbols": ["Charge", "create"]
   }
   ```
4. Click **"POST Webhook Advisory"**.
5. Sentinel immediately ingests the webhook, flags the ingestion call-sites, and prepares the migration PR.

---

### Scenario 3: GitHub Release Webhook (`POST /webhook/github`)
> **The Story:** Upstream open-source library releases a new version on GitHub, triggering an automatic release webhook to Sentinel.

#### How to Test:
```bash
curl -X POST http://localhost:8090/webhook/github \
  -H "Content-Type: application/json" \
  -d '{
    "action": "published",
    "release": {
      "tag_name": "v2.0.0",
      "name": "pydantic 2.0.0",
      "body": "Breaking: BaseModel.dict() is deprecated in favor of BaseModel.model_dump()."
    },
    "repository": {
      "name": "pydantic"
    }
  }'
```

---

### Scenario 4: Upstream PyPI Registry Scanner (Dependabot-Style)
> **The Story:** Sentinel scans the upstream PyPI registry for all imported packages in the codebase, detecting major version jumps and changelog breaking markers.

#### How to Test:
```bash
# Run on-demand from CLI
.\.venv\Scripts\python.exe -m agent sync

# Or from Dashboard UI:
# Click "Auto-Sync PyPI/GitHub" on http://localhost:3000/api-health
```

---

### Scenario 5: Fast Lineage Blast Radius Query via REST API
> **The Story:** An on-call SRE needs to know the exact business blast radius of an API vendor before approving an upgrade.

#### How to Test:
```bash
curl "http://localhost:8090/api/v1/dependencies/blast-radius?package=scikit-learn"
```

#### Output:
```json
{
  "package": "scikit-learn",
  "files": ["ml/train.py"],
  "direct_assets": ["urn:li:mlModel:(mlflow,fraud_detection_model_1,PROD)"],
  "downstream_assets": [
    {
      "name": "fraud_scoring_api",
      "entity_type": "mlModelDeployment",
      "upstream_of": "urn:li:mlModel:(mlflow,fraud_detection_model_1,PROD)"
    }
  ],
  "total_impacted": 2
}
```
