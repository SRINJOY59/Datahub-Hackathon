-- Model-ready training table: one row per transaction, enriched with user and
-- merchant features plus the fraud label. This is what the fraud model trains on
-- and what the scoring job reads features from.
select
    t.transaction_id,
    t.amount,
    u.avg_txn_amount,
    u.user_txn_count,
    u.stddev_txn_amount,
    m.merchant_fraud_rate,
    m.merchant_txn_count,
    case
        when m.merchant_category in ('crypto', 'gambling', 'gaming') then 1
        else 0
    end as is_risky_category,
    t.is_fraud
from {{ ref('stg_transactions') }}      as t
join {{ ref('feat_user_txn_stats') }}   as u on t.user_id = u.user_id
join {{ ref('feat_merchant_risk') }}    as m on t.merchant_id = m.merchant_id
