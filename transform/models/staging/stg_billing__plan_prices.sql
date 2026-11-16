-- SCD2 price list. Open-ended ranges get a far-future valid_to so range joins stay simple.
select
    plan_id,
    upper(currency)                                             as currency_code,
    cast(price as numeric(18, 4))                               as list_price,
    cast(valid_from as date)                                    as valid_from,
    coalesce(cast(valid_to as date), cast('9999-12-31' as date)) as valid_to
from {{ source('raw', 'billing_plan_prices') }}
