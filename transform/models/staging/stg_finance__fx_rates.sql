select
    cast(rate_date as date)                  as rate_date,
    upper(currency)                          as currency_code,
    cast(units_per_usd as numeric(18, 6))    as units_per_usd
from {{ source('raw', 'finance_fx_rates') }}
