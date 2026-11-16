select
    cast(spend_date as date)             as spend_date,
    upper(market)                        as market_code,
    channel                              as acquisition_channel,
    cast(spend_usd as numeric(18, 4))    as spend_usd
from {{ source('raw', 'marketing_spend') }}
