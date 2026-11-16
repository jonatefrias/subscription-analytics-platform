-- The bridge must add up every month, and each month must open where the previous one closed.
with bridge as (

    select
        *,
        lag(closing_mrr_usd) over (order by month_start) as prior_closing_mrr_usd
    from {{ ref('rpt_mrr_bridge') }}

)

select *
from bridge
where abs(opening_mrr_usd + new_mrr_usd + reactivation_mrr_usd + expansion_mrr_usd
          + contraction_mrr_usd + churned_mrr_usd - closing_mrr_usd) > 0.01
   or (prior_closing_mrr_usd is not null and abs(prior_closing_mrr_usd - opening_mrr_usd) > 0.01)
