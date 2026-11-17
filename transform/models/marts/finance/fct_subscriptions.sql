-- sqlfluff:max_line_length:220
-- (dbt.datediff renders onto one long line; the source lines are short)
select
    cast(subscription_id as varchar) as subscription_id,
    cast(customer_id as varchar) as customer_id,
    cast(plan_id as varchar) as plan_id,
    cast(market_code as varchar) as market_code,
    cast(billing_period as varchar) as billing_period,
    cast(payment_provider as varchar) as payment_provider,
    cast(subscription_number as integer) as subscription_number,
    cast(is_reactivation as boolean) as is_reactivation,
    cast(is_plan_change as boolean) as is_plan_change,
    cast(had_trial as boolean) as had_trial,
    cast(has_paid as boolean) as has_paid,
    cast(started_at as timestamp) as started_at,
    cast(trial_end_at as timestamp) as trial_end_at,
    cast(paid_from as timestamp) as paid_from,
    cast(canceled_at as timestamp) as canceled_at,
    cast(ended_at as timestamp) as ended_at,
    cast(case cancel_reason
        when 'voluntary' then 'voluntary'
        when 'payment_failed' then 'involuntary'
        when 'trial_not_converted' then 'trial'
        when 'plan_change' then 'plan_change'
    end as varchar) as end_type,
    cast(status_as_of as varchar) as status_as_of,
    cast(paid_charges as integer) as paid_charges,
    cast(gross_revenue_usd as numeric(18, 4)) as gross_revenue_usd,
    cast(refunded_usd as numeric(18, 4)) as refunded_usd,
    cast(
        {{ dbt.datediff('started_at', 'coalesce(ended_at, ' ~ as_of_ts() ~ ')', 'day') }} as integer
    ) as lifetime_days
from {{ ref('int_subscriptions__lifecycle') }}
