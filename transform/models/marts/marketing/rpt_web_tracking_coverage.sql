-- How much of the web business GA4 actually sees. Signups from the CRM (truth) vs signups
-- GA4 recorded, by signup month. The gap is mostly consent: visitors who decline analytics
-- cookies never reach GA4, so GA4 conversion counts must never be used as the signup total.
with crm as (

    select
        signup_month,
        count(*) as crm_web_signups
    from {{ ref('dim_customers') }}
    where signup_platform = 'web'
    group by 1

),

ga4 as (

    select
        cast({{ dbt.date_trunc('month', 'customers.created_at') }} as date) as signup_month,
        count(*) as ga4_signups,
        sum(case when attribution.first_touch_channel = attribution.crm_channel then 1 else 0 end)
            as first_touch_matches_crm
    from {{ ref('fct_signup_attribution') }} as attribution
    inner join {{ ref('dim_customers') }} as customers
        on customers.customer_id = attribution.customer_id
    group by 1

)

select
    crm.signup_month,
    crm.crm_web_signups,
    coalesce(ga4.ga4_signups, 0) as ga4_signups,
    cast(coalesce(ga4.ga4_signups, 0) as numeric(18, 6)) / crm.crm_web_signups as tracking_coverage,
    cast(ga4.first_touch_matches_crm as numeric(18, 6)) / nullif(ga4.ga4_signups, 0) as first_touch_agreement
from crm
left join ga4
    on ga4.signup_month = crm.signup_month
