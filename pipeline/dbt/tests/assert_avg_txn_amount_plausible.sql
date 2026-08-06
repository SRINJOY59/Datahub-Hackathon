-- Trip-wire assertion: every user's avg_txn_amount must be a plausible positive
-- dollar figure. Returns offending rows (a non-empty result = test FAILS).
-- When the incident scenario poisons upstream `amount`, this fails first and
-- becomes the agent's trigger signal.
select
    user_id,
    avg_txn_amount
from {{ ref('feat_user_txn_stats') }}
where avg_txn_amount is null
   or avg_txn_amount <= 0
   or avg_txn_amount > 10000
