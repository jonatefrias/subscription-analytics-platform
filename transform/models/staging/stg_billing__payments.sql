-- App stores report the currency in lowercase; Stripe in uppercase.
select
    payment_id,
    subscription_id,
    cast(attempt as integer)                 as attempt_number,
    status                                   as payment_status,
    cast(amount as numeric(18, 4))           as amount_local,
    upper(currency)                          as currency_code,
    cast(billed_at as timestamp)             as billed_at,
    cast(period_start as date)               as period_start,
    cast(refunded_at as timestamp)           as refunded_at,
    refunded_at is not null                  as is_refunded,
    provider                                 as payment_provider
from {{ source('raw', 'billing_payments') }}
