-- Per-user spending features. THIS is the feature table the incident scenario
-- poisons: nulling upstream `amount` silently corrupts avg_txn_amount here.
select
    user_id,
    count(*)                          as user_txn_count,
    avg(amount)                       as avg_txn_amount,
    coalesce(stddev_pop(amount), 0.0) as stddev_txn_amount,
    max(amount)                       as max_txn_amount
from {{ ref('stg_transactions') }}
group by user_id
