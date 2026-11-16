-- Month-end MRR snapshot per subscription.
-- A subscription contributes MRR at a month end if it has started paying and has not ended yet.
-- Trials do not count. Annual plans are normalised to a monthly amount.
-- MRR uses the list price in force at the snapshot and the constant FX rate.
with months as (

    select * from {{ ref('int_months') }}

),

subscriptions as (

    select * from {{ ref('int_subscriptions__lifecycle') }}
    where has_paid

),

prices as (

    select * from {{ ref('stg_billing__plan_prices') }}

),

constant_fx as (

    select * from {{ ref('int_fx__constant_rates') }}

),

active_at_month_end as (

    select
        months.month_start,
        months.snapshot_at,
        subscriptions.subscription_id,
        subscriptions.customer_id,
        subscriptions.plan_id,
        subscriptions.months_per_period
    from months
    inner join subscriptions
        on  subscriptions.paid_from < months.snapshot_at
        and (subscriptions.ended_at is null or subscriptions.ended_at > months.snapshot_at)

)

select
    active.month_start,
    active.subscription_id,
    active.customer_id,
    active.plan_id,
    prices.currency_code,
    cast(prices.list_price / active.months_per_period as numeric(18, 4))                     as mrr_local,
    cast(prices.list_price / active.months_per_period
         / constant_fx.constant_units_per_usd as numeric(18, 4))                              as mrr_usd
from active_at_month_end as active
inner join prices
    on  prices.plan_id = active.plan_id
    and cast({{ dbt.dateadd('day', -1, 'active.snapshot_at') }} as date)
        between prices.valid_from and prices.valid_to
inner join constant_fx
    on constant_fx.currency_code = prices.currency_code
