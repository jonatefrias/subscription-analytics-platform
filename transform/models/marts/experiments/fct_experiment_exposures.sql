-- One row per customer exposed to an experiment, with the outcomes used to read it.
-- Analysis (power, CUPED, intervals) lives in notebooks/; this model only provides clean inputs.
with assignments as (

    select * from {{ ref('stg_experiments__assignments') }}

),

subscriptions as (

    select * from {{ ref('fct_subscriptions') }}

),

first_30_days as (

    select
        assignments.customer_id,
        sum(payments.amount_usd_constant_fx) as revenue_first_30d_usd
    from assignments
    inner join {{ ref('fct_payments') }} as payments
        on  payments.customer_id = assignments.customer_id
        and payments.payment_status = 'paid'
        and payments.billed_at < {{ dbt.dateadd('day', 30, 'assignments.assigned_at') }}
    group by 1

)

select
    assignments.experiment_id,
    assignments.customer_id,
    assignments.variant,
    assignments.assigned_at,
    first_subscription.billing_period = 'annual'                                   as chose_annual,
    first_subscription.paid_from is not null
        and first_subscription.paid_from
            < {{ dbt.dateadd('day', var('trial_conversion_window_days'), 'assignments.assigned_at') }}
                                                                                    as paid_within_window,
    cast(coalesce(first_30_days.revenue_first_30d_usd, 0) as numeric(18, 4))       as revenue_first_30d_usd
from assignments
inner join subscriptions as first_subscription
    on  first_subscription.customer_id = assignments.customer_id
    and first_subscription.subscription_number = 1
left join first_30_days
    on first_30_days.customer_id = assignments.customer_id
