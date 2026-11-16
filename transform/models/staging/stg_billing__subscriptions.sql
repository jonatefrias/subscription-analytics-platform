select
    subscription_id,
    customer_id,
    plan_id,
    payment_provider,
    cast(started_at as timestamp)    as started_at,
    cast(trial_end_at as timestamp)  as trial_end_at,
    cast(canceled_at as timestamp)   as canceled_at,
    cast(ended_at as timestamp)      as ended_at,
    cancel_reason
from {{ source('raw', 'billing_subscriptions') }}
