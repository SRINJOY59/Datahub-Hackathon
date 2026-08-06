"""Generate deterministic synthetic raw transactions for the fraud pipeline.

Writes pipeline/dbt/seeds/raw_transactions.csv. Deterministic (fixed seed) so the
demo is reproducible. Fraud is correlated with high amounts + a set of "risky"
merchants so a real model can learn signal — which is what makes the drift demo
meaningful once a feature gets poisoned.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)

N_TXNS = 8000
N_USERS = 300
N_MERCHANTS = 60
DAYS = 120
START = datetime(2026, 4, 1)

MERCHANT_CATEGORIES = [
    "grocery", "electronics", "travel", "gaming", "crypto",
    "gambling", "restaurant", "utilities", "fashion", "pharmacy",
]
# Categories with a higher baseline fraud propensity.
RISKY_CATEGORIES = {"crypto", "gambling", "gaming"}


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def main() -> None:
    # --- merchants ---
    merchant_ids = [f"M{1000 + i}" for i in range(N_MERCHANTS)]
    merchant_category = RNG.choice(MERCHANT_CATEGORIES, size=N_MERCHANTS)
    merchant_cat = dict(zip(merchant_ids, merchant_category))

    # --- users ---
    user_ids = [f"U{10000 + i}" for i in range(N_USERS)]
    # each user has a personal spend scale (lognormal)
    user_scale = dict(zip(user_ids, RNG.lognormal(mean=3.6, sigma=0.5, size=N_USERS)))

    # --- transactions ---
    rows = []
    for i in range(N_TXNS):
        txn_id = f"T{100000 + i}"
        user = RNG.choice(user_ids)
        merchant = RNG.choice(merchant_ids)
        category = merchant_cat[merchant]

        # amount: user's personal scale, occasionally a large outlier
        base = user_scale[user]
        amount = float(RNG.lognormal(mean=np.log(base), sigma=0.6))
        if RNG.random() < 0.03:  # 3% large purchases
            amount *= RNG.uniform(4, 12)
        amount = round(amount, 2)

        # timestamp across the window
        offset_days = RNG.uniform(0, DAYS)
        ts = START + timedelta(days=float(offset_days),
                               hours=float(RNG.uniform(0, 24)))

        # fraud propensity: high amount + risky category + a little noise
        risk = (
            -4.2
            + 0.9 * (np.log1p(amount) - 4.0)
            + (1.3 if category in RISKY_CATEGORIES else 0.0)
            + RNG.normal(0, 0.4)
        )
        is_fraud = int(RNG.random() < _sigmoid(np.array(risk)))

        rows.append(
            {
                "transaction_id": txn_id,
                "user_id": user,
                "merchant_id": merchant,
                "merchant_category": category,
                "amount": amount,
                "txn_timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "is_fraud": is_fraud,
            }
        )

    df = pd.DataFrame(rows).sort_values("txn_timestamp").reset_index(drop=True)

    out_dir = os.path.join(os.path.dirname(__file__), "dbt", "seeds")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "raw_transactions.csv")
    df.to_csv(out_path, index=False)

    print(f"Wrote {len(df)} transactions -> {out_path}")
    print(f"Fraud rate: {df['is_fraud'].mean():.3%}")
    print(f"Users: {df['user_id'].nunique()}  Merchants: {df['merchant_id'].nunique()}")
    print(f"Amount range: {df['amount'].min():.2f} .. {df['amount'].max():.2f}")


if __name__ == "__main__":
    main()
