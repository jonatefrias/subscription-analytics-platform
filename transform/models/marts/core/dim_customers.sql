with customers as (

    select * from {{ ref('stg_crm__customers') }}

),

subscriptions as (

    select * from {{ ref('int_subscriptions__lifecycle') }}

),

first_subscription as (

    select * from subscriptions where subscription_number = 1

),

rollup as (

    select
        customer_id,
        count(*)                                                                as subscriptions,
        sum(case when is_reactivation then 1 else 0 end)                        as reactivations,
        min(paid_from)                                                          as first_paid_at,
        sum(gross_revenue_usd - refunded_usd)                                   as net_revenue_usd,
        max(case when status_as_of in ('active', 'non_renewing') and has_paid then 1 else 0 end) as is_paying,
        max(case when status_as_of = 'trialing' then 1 else 0 end)              as is_trialing
    from subscriptions
    group by 1

)

select
    cast(customers.customer_id as varchar)                         as customer_id,
    cast(customers.created_at as timestamp)                        as created_at,
    cast({{ dbt.date_trunc('month', 'customers.created_at') }} as date) as signup_month,
    cast(customers.country_code as varchar)                        as market_code,
    cast(customers.signup_platform as varchar)                     as signup_platform,
    cast(customers.acquisition_channel as varchar)                 as acquisition_channel,
    cast(matches.match_date is not null as boolean)                as is_big_match_signup,
    cast(first_subscription.billing_period as varchar)             as first_billing_period,
    cast(first_subscription.had_trial as boolean)                  as started_with_trial,
    cast(first_subscription.had_trial and first_subscription.has_paid
         and first_subscription.paid_from <= {{ dbt.dateadd('day', var('trial_conversion_window_days'), 'first_subscription.started_at') }}
         as boolean)                                               as converted_from_trial,
    cast(rollup.first_paid_at as timestamp)                        as first_paid_at,
    cast(rollup.subscriptions as integer)                          as subscriptions,
    cast(rollup.reactivations as integer)                          as reactivations,
    cast(rollup.net_revenue_usd as numeric(18, 4))                 as lifetime_net_revenue_usd,
    cast(case
        when rollup.is_paying = 1 then 'paying'
        when rollup.is_trialing = 1 then 'trialing'
        when rollup.first_paid_at is null then 'never_paid'
        else 'churned'
    end as varchar)                                                as status_as_of
from customers
inner join rollup
    on rollup.customer_id = customers.customer_id
inner join first_subscription
    on first_subscription.customer_id = customers.customer_id
left join {{ ref('big_match_days') }} as matches
    on matches.match_date = cast(customers.created_at as date)
