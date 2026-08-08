"""Seed the incident store and action journal with realistic, varied incidents.

This writes REAL data into .sentinel/incidents.db and .sentinel/journal.jsonl
— the same stores the agent uses. Run once to populate the dashboard.

Usage:
    python scripts/seed_incidents.py
"""
from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Script lives in scripts/ so parent is REPO_ROOT
REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / ".sentinel" / "incidents.db"
JOURNAL_PATH = REPO_ROOT / ".sentinel" / "journal.jsonl"

# ---------------------------------------------------------------------------
# Realistic data pools
# ---------------------------------------------------------------------------
ASSET_POOL = [
    ("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.stg_transactions,PROD)", "stg_transactions"),
    ("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.dim_customers,PROD)", "dim_customers"),
    ("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.fct_revenue,PROD)", "fct_revenue"),
    ("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.fct_daily_fraud_summary,PROD)", "fct_daily_fraud_summary"),
    ("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.dim_merchants,PROD)", "dim_merchants"),
    ("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.stg_user_features,PROD)", "stg_user_features"),
    ("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.raw_transactions,PROD)", "raw_transactions"),
    ("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.fct_chargeback_rate,PROD)", "fct_chargeback_rate"),
    ("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.dim_payment_methods,PROD)", "dim_payment_methods"),
    ("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.fct_merchant_risk_score,PROD)", "fct_merchant_risk_score"),
    ("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.stg_card_events,PROD)", "stg_card_events"),
    ("urn:li:dataset:(urn:li:dataPlatform:dbt,analytics.fct_transaction_velocity,PROD)", "fct_transaction_velocity"),
]

CHANGE_TYPES = [
    "null_spike", "scale_shift", "range_violation", "schema_change",
    "distribution_drift", "dependency_change", "code_change",
    "training_regression", "model_drift", "freshness_lag",
    "volume_anomaly", "label_leakage", "duplicate_records",
    "training_serving_skew",
]

SIGNAL_TYPES = [
    "assertion_failure", "schema_change", "freshness", "model_drift",
    "dependency_change", "code_change", "training_regression",
    "volume_anomaly", "label_leakage", "training_serving_skew",
]

ACTION_TYPES = [
    "quarantine", "pin_feature", "tag_asset", "pause_job",
    "repoint_model", "dedupe_partition",
]

TIERS = ["auto", "pr_only", "human_only"]
CONFIDENCES = ["high", "medium", "low"]

STATUSES_RESOLVED = ["resolved", "contained", "rolled_back"]
STATUSES_OPEN = ["open", "escalated"]

NARRATIVES = [
    "The upstream data provider changed the schema of the {column} column in {table}, causing null values to propagate through the feature pipeline. The assertion caught the anomaly within 2 minutes of the batch landing.",
    "A batch replay from the payment processor delivered duplicate records for the {date_range} window. Row counts in {table} jumped 2.3x, inflating downstream aggregates including the daily fraud summary.",
    "The {column} values in {table} shifted from dollars to cents after a provider-side API update. This 100x scale shift tripped the range assertion and would have corrupted the merchant risk scores.",
    "Freshness SLA breach on {table}: the last successful load was {hours}h ago. The upstream Airflow DAG failed silently, leaving stale data flowing into the fraud detection model.",
    "Distribution drift detected in {table}.{column}: the mean shifted from {old_mean} to {new_mean} over the last 24h. This correlates with a new merchant category being onboarded without updating the feature encoding.",
    "The fraud detection model's prediction distribution shifted significantly — positive rate moved from 2.1% to 8.7%. Root cause traces to a training data contamination where test labels leaked into the feature set.",
    "Volume collapse in {table}: row count dropped from ~45K/day to 312 rows. The upstream CDC connector lost its replication slot and was silently producing empty batches.",
    "A dependency update (stripe-python 8.x -> 9.x) changed the response schema for charge objects. The amount_captured field moved from cents to a nested Money object, breaking the ingestion parser.",
    "Training regression detected: the champion model's F1 score dropped from 0.847 to 0.712 after retraining on the latest 30-day window. Root cause is the null spike in transaction amounts that contaminated the training set.",
    "Schema change in {table}: column {column} was renamed to {column}_v2 by the upstream team without notice. The dbt model still references the old name, producing NULL for all rows.",
    "The scoring pipeline detected training/serving skew: the user_tenure_days feature has mean=847 at training time but mean=12.3 at serving time. The serving pipeline is reading from a different source table.",
    "Code change in the dbt model for {table}: a recent commit altered the JOIN condition from LEFT JOIN to INNER JOIN, silently dropping 15% of records that had no matching dimension row.",
]

COST_BASES = [
    "{n} downstream consumers x {hours}h exposure x ${rate}/hr estimated business impact",
    "SLA breach penalty: ${penalty} per hour x {hours}h downtime + {n} affected customer reports",
    "Revenue at risk: {pct}% of daily GMV ({gmv}) exposed to incorrect fraud scoring for {hours}h",
    "Model retraining cost (${retrain}) + rollback engineering time ({hours}h x ${rate}/hr)",
    "Estimated data quality impact: {rows} rows affected x ${per_row} downstream value per row",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _random_dt(days_ago_min: int, days_ago_max: int) -> datetime:
    delta = random.uniform(days_ago_min * 24 * 60, days_ago_max * 24 * 60)
    return datetime.now(timezone.utc) - timedelta(minutes=delta)


def _make_incident_id(change_type: str, seq: int) -> str:
    prefixes = {
        "null_spike": "INC",
        "scale_shift": "INC",
        "range_violation": "INC",
        "schema_change": "SCH",
        "distribution_drift": "DFT",
        "dependency_change": "DEP",
        "code_change": "CHG",
        "training_regression": "TRN",
        "model_drift": "DRIFT",
        "freshness_lag": "FRS",
        "volume_anomaly": "VOL",
        "label_leakage": "LBL",
        "duplicate_records": "DUP",
        "training_serving_skew": "SKW",
    }
    prefix = prefixes.get(change_type, "INC")
    return f"{prefix}-{random.randint(1000, 9999)}"


def _pick_narrative(asset_name: str) -> str:
    template = random.choice(NARRATIVES)
    return template.format(
        column=random.choice(["amount", "user_id", "merchant_id", "txn_timestamp", "category", "risk_score", "tenure_days"]),
        table=asset_name,
        date_range=f"{random.randint(1, 28)} Jan - {random.randint(1, 28)} Feb",
        hours=round(random.uniform(0.5, 48), 1),
        old_mean=round(random.uniform(10, 500), 1),
        new_mean=round(random.uniform(10, 500), 1),
        column_v2=random.choice(["amount_v2", "user_id_new", "merchant_code"]),
    )


def _pick_cost_basis() -> str:
    template = random.choice(COST_BASES)
    return template.format(
        n=random.randint(3, 25),
        hours=round(random.uniform(0.5, 12), 1),
        rate=random.choice([150, 200, 250, 300]),
        penalty=random.choice([500, 1000, 2500, 5000]),
        pct=round(random.uniform(0.5, 5), 1),
        gmv=f"${random.randint(50, 500)}K",
        retrain=random.randint(200, 2000),
        rows=f"{random.randint(1, 50)}K",
        per_row=round(random.uniform(0.01, 0.50), 2),
    )


def generate_incidents(count: int = 35) -> list[dict]:
    incidents = []

    for i in range(count):
        asset_urn, asset_name = random.choice(ASSET_POOL)
        change_type = random.choice(CHANGE_TYPES)
        signal_type = random.choice(SIGNAL_TYPES)

        days_ago = random.triangular(0, 30, 3)
        detected_at = datetime.now(timezone.utc) - timedelta(days=days_ago)

        if random.random() < 0.80:
            close_minutes = random.triangular(1, 45, 8)
            closed_at = detected_at + timedelta(minutes=close_minutes)
            status = random.choice(STATUSES_RESOLVED)
            resolved = 1 if status == "resolved" else 0
        else:
            closed_at = None
            status = random.choice(STATUSES_OPEN)
            resolved = 0

        tier = random.choices(TIERS, weights=[60, 25, 15])[0]
        confidence = random.choices(CONFIDENCES, weights=[50, 35, 15])[0]
        cost_usd = round(random.triangular(500, 25000, 4000), 0)
        downstream_count = random.randint(1, 18)

        num_actions = random.randint(1, 3)
        actions = random.sample(ACTION_TYPES, min(num_actions, len(ACTION_TYPES)))

        incident_id = _make_incident_id(change_type, i)
        while any(inc["id"] == incident_id for inc in incidents):
            incident_id = _make_incident_id(change_type, i + random.randint(100, 999))

        root_cause_columns = ["amount", "user_id", "merchant_id", "txn_timestamp",
                              "category", "risk_score", "tenure_days", "channel_code"]

        incidents.append({
            "id": incident_id,
            "asset_urn": asset_urn,
            "asset_name": asset_name,
            "signal_type": signal_type,
            "summary": f"{change_type.replace('_', ' ')} detected on {asset_name}",
            "change_type": change_type,
            "confidence": confidence,
            "narrative": _pick_narrative(asset_name),
            "root_cause_asset": asset_urn,
            "root_cause_column": random.choice(root_cause_columns),
            "tier": tier,
            "status": status,
            "resolved": resolved,
            "pr": f"https://github.com/acme/data-platform/pull/{random.randint(100, 999)}" if status == "resolved" and random.random() < 0.3 else None,
            "cost_usd": cost_usd,
            "cost_basis": _pick_cost_basis(),
            "downstream_count": downstream_count,
            "actions": json.dumps(actions),
            "detected_at": detected_at.isoformat(),
            "closed_at": closed_at.isoformat() if closed_at else None,
            "updated_at": (closed_at or detected_at).isoformat(),
        })

    return incidents


def generate_journal_entries(incidents: list[dict]) -> list[dict]:
    entries = []

    for inc in incidents:
        actions = json.loads(inc["actions"])
        detected = datetime.fromisoformat(inc["detected_at"])

        for j, action_type in enumerate(actions):
            applied_at = detected + timedelta(minutes=random.uniform(0.5, 5) * (j + 1))

            if inc["status"] == "resolved":
                status = "applied"
            elif inc["status"] == "rolled_back":
                status = random.choice(["applied", "reverted"])
            elif inc["status"] == "contained":
                status = "applied"
            elif inc["status"] == "escalated":
                status = random.choice(["applied", "failed"])
            else:
                status = random.choice(["applied", "simulated"])

            notes = {
                "quarantine": f"quarantined bad partition in {inc['asset_name']} - {random.randint(100, 5000)} rows isolated",
                "pin_feature": f"pinned {inc['asset_name']} to last-known-good snapshot at {(detected - timedelta(hours=random.randint(1, 24))).strftime('%Y-%m-%d %H:%M')}",
                "tag_asset": f"tagged {inc['asset_name']} and {inc['downstream_count']} downstream assets as Sentinel-Degraded",
                "pause_job": f"paused scoring job consuming {inc['asset_name']} to prevent bad predictions from reaching production",
                "repoint_model": f"repointed fraud_detection_model to version {random.randint(1, 20)} (last known good)",
                "dedupe_partition": f"deduped {random.randint(500, 8000)} duplicate records from {inc['asset_name']} partition {detected.strftime('%Y-%m-%d')}",
            }

            entry = {
                "action_type": action_type,
                "target": inc["asset_urn"],
                "params": {},
                "inverse": {
                    "action_type": action_type,
                    "target": inc["asset_urn"],
                    "params": {"restore": True},
                    "inverse": None,
                    "applied_at": None,
                    "note": f"undo {action_type}",
                    "incident_id": inc["id"],
                    "status": "planned",
                } if action_type not in ("tag_asset",) else None,
                "applied_at": applied_at.isoformat(),
                "note": notes.get(action_type, f"{action_type} on {inc['asset_name']}"),
                "incident_id": inc["id"],
                "status": status,
            }
            entries.append(entry)

            if status == "reverted":
                revert_at = applied_at + timedelta(minutes=random.uniform(2, 15))
                entries.append({
                    "action_type": action_type,
                    "target": inc["asset_urn"],
                    "params": {},
                    "inverse": None,
                    "applied_at": revert_at.isoformat(),
                    "note": f"reverted {action_type}",
                    "incident_id": inc["id"],
                    "status": "reverted",
                })

    return entries


def seed(count: int = 35):
    print(f"Generating {count} incidents...")
    incidents = generate_incidents(count)

    print("Generating journal entries...")
    journal_entries = generate_journal_entries(incidents)

    print(f"\nWriting {len(incidents)} incidents to {DB_PATH}...")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    cols = [
        "id", "asset_urn", "asset_name", "signal_type", "summary",
        "change_type", "confidence", "narrative", "root_cause_asset",
        "root_cause_column", "tier", "status", "resolved", "pr",
        "cost_usd", "cost_basis", "downstream_count", "actions",
        "detected_at", "closed_at", "updated_at",
    ]
    placeholders = ", ".join(f":{c}" for c in cols)
    col_names = ", ".join(cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")

    inserted = 0
    for inc in incidents:
        try:
            conn.execute(
                f"INSERT INTO incidents ({col_names}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                inc,
            )
            inserted += 1
        except Exception as e:
            print(f"  WARN: skipped {inc['id']}: {e}")

    conn.commit()
    conn.close()
    print(f"  OK: {inserted} incidents written")

    print(f"\nAppending {len(journal_entries)} journal entries to {JOURNAL_PATH}...")
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a", encoding="utf-8") as fh:
        for entry in journal_entries:
            fh.write(json.dumps(entry) + "\n")
    print(f"  OK: {len(journal_entries)} entries appended")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(resolved) AS resolved,
            SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_count,
            SUM(COALESCE(cost_usd, 0)) AS exposure,
            AVG(CASE WHEN closed_at IS NOT NULL
                THEN (julianday(closed_at) - julianday(detected_at)) * 24 * 60
            END) AS mttr
        FROM incidents
    """).fetchone()
    conn.close()

    print(f"\n{'='*60}")
    print(f"  Store summary after seeding:")
    print(f"    Total incidents:    {row['total']}")
    print(f"    Resolved:           {row['resolved']}")
    print(f"    Open:               {row['open_count']}")
    print(f"    Total exposure:     ${row['exposure']:,.0f}")
    if row['mttr']:
        print(f"    Mean time to close: {row['mttr']:.1f} min")
    print(f"{'='*60}")

    if JOURNAL_PATH.exists():
        n = sum(1 for _ in JOURNAL_PATH.open(encoding="utf-8"))
        print(f"  Journal now has {n} total entries")

    print("\nDone! Refresh the dashboard to see the data.")


if __name__ == "__main__":
    seed()
