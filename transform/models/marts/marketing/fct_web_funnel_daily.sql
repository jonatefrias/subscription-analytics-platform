-- Day x market x session channel funnel. Additive counts only; rates belong to the metrics layer.
select
    session_date                                                     as activity_date,
    coalesce(market_code, 'unknown')                                 as market_code,
    channel,
    count(*)                                                         as sessions,
    sum(case when is_engaged then 1 else 0 end)                      as engaged_sessions,
    sum(case when reached_paywall then 1 else 0 end)                 as paywall_sessions,
    sum(case when selected_plan then 1 else 0 end)                   as plan_selected_sessions,
    sum(case when signed_up then 1 else 0 end)                       as signup_sessions,
    sum(case when started_trial then 1 else 0 end)                   as trial_sessions,
    sum(case when purchased then 1 else 0 end)                       as purchase_sessions
from {{ ref('fct_web_sessions') }}
group by 1, 2, 3
