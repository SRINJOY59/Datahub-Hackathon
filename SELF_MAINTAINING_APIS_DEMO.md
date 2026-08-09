# Self-Maintaining APIs — Hackathon Demo Guide

Here are **4 production-grade demo scenarios** designed to give hackathon judges a realistic experience of **Self-Maintaining APIs**:

---

### Scenario 1: The ML Champion Model API Break (`scikit-learn 2.0`)
> **The Story:** A vendor releases a breaking change in an ML library that our fraud-detection training pipeline imports.

#### How the Judges Test It:
```bash
# 1. Inject the breaking change advisory
python -m scenarios api_breaking_change

# 2. Run the autonomous Sentinel agent
python -m agent
```

#### What Judges See:
1. **Terminal**: Sentinel catches `DEP-scikit-l`, maps call-sites in `ml/train.py`, traces the DataHub blast radius to `fraud_detection_model_1` $\to$ `fraud_scoring_api`, and generates a validated diff.
2. **Dashboard (`http://localhost:3000/api-health`)**:
   - **Active Advisories Tab**: Shows scikit-learn advisory with highlighted call-site `ml/train.py:42`.
   - **Lineage Blast Radius Tab**: Displays the 4-step DAG showing that breaking `scikit-learn` puts our live fraud-scoring API at risk ($3,000 exposure avoided).
   - **Migration History Tab**: Click **"View Generated Diff"** to inspect the LLM-generated code fix.

---

### Scenario 2: Live Payment Gateway SDK Migration (`stripe v10.0`)
> **The Story:** Stripe sends a live webhook announcing that `stripe.Charge.create()` is deprecated in favor of `stripe.PaymentIntent.create()`.

#### How the Judges Test It (Live from the UI):
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
5. Click **"SRE Scan Now"**.

#### What Judges See:
- The package `stripe` immediately transitions from `Healthy` to `At Risk` in the Dependency Inventory.
- Sentinel registers the advisory, flags the ingestion call-sites, and prepares the migration PR.

---

### Scenario 3: Multi-File Framework Refactor (`pydantic v2`)
> **The Story:** Pydantic deprecates `.dict()` across multiple API routes and schemas in favor of `.model_dump()`.

#### How the Judges Test It (Multi-File CodeFix Demo):
Run this `curl` command to post the advisory:
```bash
curl -X POST http://localhost:8090/api/v1/advisory \
  -H "Content-Type: application/json" \
  -d '{
    "package": "pydantic",
    "from_version": "1.10.0",
    "to_version": "2.0.0",
    "summary": "BaseModel.dict() deprecated in favor of BaseModel.model_dump()",
    "migration": "Replace .dict() method calls with .model_dump() on all Pydantic model instances",
    "symbols": ["dict", "BaseModel"]
  }'
```

#### What Judges See:
- **Multi-File Detection**: Sentinel scans the repository and finds call-sites across `api/advisory_routes.py`, `api/types.py`, and `agent/contracts.py`.
- **Multi-File PR**: Sentinel runs shadow validation on each file and creates a single unified PR covering all affected files simultaneously.

---

### Scenario 4: Fast Lineage Query via REST API (SRE Tooling)
> **The Story:** An on-call SRE needs to know the exact business blast radius of an API vendor before approving an upgrade.

#### How the Judges Test It:
```bash
curl "http://localhost:8090/api/v1/dependencies/blast-radius?package=scikit-learn"
```

#### What Judges Get:
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

---

### Scenario 5: Automated PyPI / GitHub Registry Monitoring
> **The Story:** Sentinel autonomously monitors upstream PyPI and GitHub releases in the background, auto-detecting major version upgrades without requiring manual webhook payload authoring.

#### How the Judges Test It:
1. Navigate to **`http://localhost:3000/api-health`**.
2. Click **"Auto-Sync PyPI/GitHub"** in the top action bar (or call `POST http://localhost:8090/api/v1/advisories/sync-registry`).
3. Sentinel queries PyPI's live registry, checks installed versions against latest releases, and automatically generates breaking-change advisories.
4. **Dual-Trigger Architecture & Resilience:** If external registry network is unreachable or rate-limited, Sentinel seamlessly falls back to registry cache, and the **"Ingest Vendor Webhook"** UI button remains fully operational for on-demand simulation.

---

### 💡 Quick Tip for Hackathon Presentation
1. Start on **`/api-health`** to show the healthy inventory of watched packages.
2. Click **"Auto-Sync PyPI/GitHub"** to demonstrate automatic upstream release tracking.
3. Use **"Ingest Vendor Webhook"** to simulate an incoming webhook from Stripe or scikit-learn.
4. Show the live **Lineage Blast Radius DAG** to showcase the DataHub differentiator.
5. Run **"SRE Scan Now"** to generate the multi-file migration diff and open the GitHub PR.
