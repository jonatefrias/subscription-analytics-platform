-- One row per customer whose signup GA4 observed, with the touchpoints that led to it.
-- Touchpoints are the customer's stitched sessions up to and including the signup session.
--   first touch        : the earliest touchpoint
--   last non-direct    : the latest touchpoint that was not direct (direct only if all were)
-- The CRM channel is kept next to them, because the CRM stores what the customer told
-- us at signup, which is closer to first touch.
with sessions as (

    select * from {{ ref('fct_web_sessions') }}
    where customer_id is not null

),

signup_session as (

    select customer_id, min(session_started_at) as signup_session_at
    from sessions
    where signed_up
    group by 1

),

touchpoints as (

    select
        sessions.customer_id,
        sessions.session_started_at,
        sessions.channel,
        sessions.source,
        signup_session.signup_session_at,
        row_number() over (partition by sessions.customer_id order by sessions.session_started_at) as touch_order,
        row_number() over (
            partition by sessions.customer_id
            order by case when sessions.channel = 'direct' then 1 else 0 end, sessions.session_started_at desc
        )                                                                                          as last_non_direct_rank,
        count(*) over (partition by sessions.customer_id)                                          as touchpoints
    from sessions
    inner join signup_session
        on  signup_session.customer_id = sessions.customer_id
        and sessions.session_started_at <= signup_session.signup_session_at

),

attributed as (

    select
        customer_id,
        max(signup_session_at)                                                as signup_session_at,
        max(touchpoints)                                                      as touchpoints,
        min(session_started_at)                                               as first_touch_at,
        max(case when touch_order = 1 then channel end)                       as first_touch_channel,
        max(case when touch_order = 1 then source end)                        as first_touch_source,
        max(case when last_non_direct_rank = 1 then channel end)              as last_non_direct_channel,
        max(case when last_non_direct_rank = 1 then source end)               as last_non_direct_source
    from touchpoints
    group by 1

)

select
    attributed.customer_id,
    attributed.signup_session_at,
    attributed.touchpoints,
    attributed.first_touch_at,
    {{ dbt.datediff('attributed.first_touch_at', 'attributed.signup_session_at', 'day') }} as days_first_touch_to_signup,
    attributed.first_touch_channel,
    attributed.first_touch_source,
    attributed.last_non_direct_channel,
    attributed.last_non_direct_source,
    customers.acquisition_channel                                                           as crm_channel,
    customers.market_code
from attributed
inner join {{ ref('dim_customers') }} as customers
    on customers.customer_id = attributed.customer_id
