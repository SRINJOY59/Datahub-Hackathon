-- Distribution trip-wire: the recent-window average amount must stay within 50%
-- of the historical average. Catches subtle drift (and scale/null breaks) that a
-- plain range check misses. Non-empty result = test FAILS.
with cutoff as (
    select quantile_cont(epoch(txn_timestamp), 0.8) as c from stg_transactions
),
recent as (
    select avg(amount) as a from stg_transactions, cutoff
    where epoch(txn_timestamp) >= cutoff.c
),
hist as (
    select avg(amount) as a from stg_transactions, cutoff
    where epoch(txn_timestamp) < cutoff.c
)
select recent.a as recent_avg, hist.a as hist_avg
from recent, hist
where hist.a is null
   or hist.a = 0
   or recent.a is null
   or abs(recent.a - hist.a) / hist.a > 0.5
