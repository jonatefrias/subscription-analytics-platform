-- Monthly MRR bridge: opening + new + reactivation + expansion - contraction - churn = closing.
-- Ratios (ARPU, churn rates) are computed here for convenience; the semantic layer is the
-- source of truth for metric definitions.
with movements as (

    select * from {{ ref('fct_mrr_monthly') }}

),

monthly as (

    select
        month_start,
        sum(previous_mrr_usd) as opening_mrr_usd,
        sum(case when movement_type = 'new' then mrr_change_usd else 0 end) as new_mrr_usd,
        sum(case when movement_type = 'reactivation' then mrr_change_usd else 0 end) as reactivation_mrr_usd,
        sum(case when movement_type = 'expansion' then mrr_change_usd else 0 end) as expansion_mrr_usd,
        sum(case when movement_type = 'contraction' then mrr_change_usd else 0 end) as contraction_mrr_usd,
        sum(case when movement_type = 'churn' then mrr_change_usd else 0 end) as churned_mrr_usd,
        sum(mrr_usd) as closing_mrr_usd,
        sum(case when previous_mrr_usd > 0 then 1 else 0 end) as opening_customers,
        sum(case when mrr_usd > 0 then 1 else 0 end) as closing_customers,
        sum(case when movement_type = 'new' then 1 else 0 end) as new_customers,
        sum(case when movement_type = 'reactivation' then 1 else 0 end) as reactivated_customers,
        sum(case when movement_type = 'churn' then 1 else 0 end) as churned_customers
    from movements
    group by 1

)

select
    *,
    closing_mrr_usd / nullif(closing_customers, 0) as arpu_usd,
    cast(churned_customers as numeric(18, 6)) / nullif(opening_customers, 0) as logo_churn_rate,
    -- gross churn counts every dollar lost from the opening base: churn and contraction
    -(churned_mrr_usd + contraction_mrr_usd) / nullif(opening_mrr_usd, 0) as gross_mrr_churn_rate
from monthly
