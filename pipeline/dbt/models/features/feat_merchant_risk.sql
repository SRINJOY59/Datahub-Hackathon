-- Per-merchant risk features derived from historical fraud rate.
select
    merchant_id,
    merchant_category,
    count(*)        as merchant_txn_count,
    avg(is_fraud)   as merchant_fraud_rate
from {{ ref('stg_transactions') }}
group by merchant_id, merchant_category
