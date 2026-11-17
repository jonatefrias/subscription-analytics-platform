-- Day x market x channel funnel with spend. Only additive measures live here;
-- CAC and conversion rates are ratios and belong in the metrics layer.
with customers as (

    select * from {{ ref('dim_customers') }}

),

funnel as (

    select
        cast(created_at as date) as activity_date,
        market_code,
        acquisition_channel,
        count(*) as signups,
        sum(case when started_with_trial then 1 else 0 end) as trials_started,
        sum(case when converted_from_trial then 1 else 0 end) as trials_converted,
        sum(case when first_paid_at is not null then 1 else 0 end) as paying_customers_acquired
    from customers
    group by 1, 2, 3

),

spend as (

    select
        spend_date as activity_date,
        market_code,
        acquisition_channel,
        sum(spend_usd) as spend_usd
    from {{ ref('stg_marketing__spend') }}
    group by 1, 2, 3

)

select
    coalesce(funnel.activity_date, spend.activity_date) as activity_date,
    coalesce(funnel.market_code, spend.market_code) as market_code,
    coalesce(funnel.acquisition_channel, spend.acquisition_channel) as acquisition_channel,
    coalesce(funnel.signups, 0) as signups,
    coalesce(funnel.trials_started, 0) as trials_started,
    coalesce(funnel.trials_converted, 0) as trials_converted,
    coalesce(funnel.paying_customers_acquired, 0) as paying_customers_acquired,
    cast(coalesce(spend.spend_usd, 0) as numeric(18, 4)) as spend_usd
from funnel
full outer join spend
    on spend.activity_date = funnel.activity_date
        and spend.market_code = funnel.market_code
        and spend.acquisition_channel = funnel.acquisition_channel
