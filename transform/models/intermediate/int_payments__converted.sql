-- Charges converted to USD twice: at the FX rate of the billing day (actuals)
-- and at the constant budget rate (for like-for-like comparisons).
with payments as (

    select * from {{ ref('stg_billing__payments') }}

),

daily_fx as (

    select * from {{ ref('stg_finance__fx_rates') }}

),

constant_fx as (

    select * from {{ ref('int_fx__constant_rates') }}

)

select
    payments.*,
    cast(payments.amount_local / daily_fx.units_per_usd as numeric(18, 4))        as amount_usd,
    cast(payments.amount_local / constant_fx.constant_units_per_usd as numeric(18, 4)) as amount_usd_constant_fx
from payments
left join daily_fx
    on  daily_fx.currency_code = payments.currency_code
    and daily_fx.rate_date = cast(payments.billed_at as date)
left join constant_fx
    on constant_fx.currency_code = payments.currency_code
