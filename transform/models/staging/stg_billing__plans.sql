select
    plan_id,
    plan_name,
    upper(market) as market_code,
    billing_period,
    case billing_period when 'annual' then 12 else 1 end as months_per_period,
    cast(trial_days as integer) as trial_days
from {{ source('raw', 'billing_plans') }}
