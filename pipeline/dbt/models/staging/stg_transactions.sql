-- Cleaned, typed transaction stream. One row per transaction.
select
    transaction_id,
    user_id,
    merchant_id,
    merchant_category,
    cast(amount as double)          as amount,
    cast(txn_timestamp as timestamp) as txn_timestamp,
    cast(is_fraud as integer)        as is_fraud
from {{ ref('raw_transactions') }}
