-- Budget ("constant") FX rate per currency: the average of the reference year.
-- Reporting MRR at constant FX keeps currency swings from showing up as expansion or churn.
select
    currency_code,
    cast(avg(units_per_usd) as numeric(18, 6)) as constant_units_per_usd
from {{ ref('stg_finance__fx_rates') }}
where extract(year from rate_date) = {{ var('constant_fx_year') }}
group by 1
