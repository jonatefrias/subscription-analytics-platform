-- Month-end MRR per customer (a customer can briefly hold two subscriptions).
select
    customer_id,
    month_start,
    count(*)                                  as active_subscriptions,
    cast(sum(mrr_usd) as numeric(18, 4))      as mrr_usd
from {{ ref('int_mrr__subscription_months') }}
group by 1, 2
