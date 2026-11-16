with payments as (

    select * from {{ ref('int_payments__converted') }}

),

subscriptions as (

    select subscription_id, customer_id, plan_id, market_code
    from {{ ref('int_subscriptions__lifecycle') }}

)

select
    cast(payments.payment_id as varchar)                as payment_id,
    cast(payments.subscription_id as varchar)           as subscription_id,
    cast(subscriptions.customer_id as varchar)          as customer_id,
    cast(subscriptions.plan_id as varchar)              as plan_id,
    cast(subscriptions.market_code as varchar)          as market_code,
    cast(payments.payment_provider as varchar)          as payment_provider,
    cast(payments.attempt_number as integer)            as attempt_number,
    cast(payments.payment_status as varchar)            as payment_status,
    cast(payments.billed_at as timestamp)               as billed_at,
    cast(payments.period_start as date)                 as period_start,
    cast(payments.currency_code as varchar)             as currency_code,
    cast(payments.amount_local as numeric(18, 4))       as amount_local,
    cast(payments.amount_usd as numeric(18, 4))         as amount_usd,
    cast(payments.amount_usd_constant_fx as numeric(18, 4)) as amount_usd_constant_fx,
    cast(payments.is_refunded as boolean)               as is_refunded,
    cast(payments.refunded_at as timestamp)             as refunded_at
from payments
inner join subscriptions
    on subscriptions.subscription_id = payments.subscription_id
