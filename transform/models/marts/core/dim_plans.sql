with plans as (

    select * from {{ ref('stg_billing__plans') }}

),

current_prices as (

    select * from {{ ref('stg_billing__plan_prices') }}
    where {{ as_of_date() }} between valid_from and valid_to

)

select
    plans.plan_id,
    plans.plan_name,
    plans.market_code,
    plans.billing_period,
    plans.months_per_period,
    plans.trial_days,
    current_prices.currency_code,
    current_prices.list_price as current_list_price,
    cast(current_prices.list_price / plans.months_per_period as numeric(18, 4)) as current_monthly_equivalent
from plans
left join current_prices
    on current_prices.plan_id = plans.plan_id
