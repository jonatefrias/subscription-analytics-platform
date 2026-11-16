-- One row per GA4 session (cookie + ga_session_id) with its traffic source, landing
-- context and funnel steps. The traffic source is read from the session's first event,
-- which is where GA4 records the campaign parameters.
with events as (

    select * from {{ ref('stg_ga4__events') }}

),

first_event as (

    select *
    from (
        select
            events.*,
            row_number() over (partition by session_key order by event_at, event_name) as event_rank
        from events
    ) as ranked
    where event_rank = 1

),

session_rollup as (

    select
        session_key,
        min(event_at)                                                                as session_started_at,
        max(event_at)                                                                as session_ended_at,
        sum(case when event_name = 'page_view' then 1 else 0 end)                    as page_views,
        coalesce(sum(engagement_time_msec), 0) / 1000.0                              as engagement_seconds,
        max(case when event_name = 'view_paywall' then 1 else 0 end) = 1             as reached_paywall,
        max(case when event_name = 'select_plan' then 1 else 0 end) = 1              as selected_plan,
        max(case when event_name = 'sign_up' then 1 else 0 end) = 1                 as signed_up,
        max(case when event_name = 'start_trial' then 1 else 0 end) = 1              as started_trial,
        max(case when event_name = 'purchase' then 1 else 0 end) = 1                 as purchased,
        max(case when event_name = 'login' then 1 else 0 end) = 1                    as logged_in,
        max(user_id)                                                                 as session_user_id,
        sum(case when event_name = 'purchase' then purchase_value else 0 end)        as purchase_value
    from events
    group by 1

),

aliases as (

    select * from {{ ref('ga4_source_aliases') }}

),

countries as (

    select * from {{ ref('countries') }}

)

select
    session_rollup.session_key,
    first_event.user_pseudo_id,
    first_event.ga_session_id,
    first_event.ga_session_number,
    session_rollup.session_started_at,
    session_rollup.session_ended_at,
    first_event.device_category,
    countries.country_code                                            as market_code,
    coalesce(aliases.canonical_source, first_event.source_raw, '(direct)') as source,
    coalesce(first_event.medium, '(none)')                            as medium,
    first_event.campaign,
    case
        when first_event.medium = 'paid_social'                       then 'paid_social'
        when first_event.medium = 'cpc'                               then 'paid_search'
        when first_event.medium = 'organic'                           then 'organic'
        when first_event.medium = 'referral'                          then 'referral'
        when first_event.medium = 'partner'                           then 'partner'
        when first_event.source_raw is null and first_event.medium is null then 'direct'
        else 'other'
    end                                                               as channel,
    session_rollup.page_views,
    session_rollup.engagement_seconds,
    session_rollup.page_views >= 2 or session_rollup.engagement_seconds >= 10 as is_engaged,
    session_rollup.reached_paywall,
    session_rollup.selected_plan,
    session_rollup.signed_up,
    session_rollup.started_trial,
    session_rollup.purchased,
    session_rollup.logged_in,
    session_rollup.session_user_id,
    session_rollup.purchase_value
from session_rollup
inner join first_event
    on first_event.session_key = session_rollup.session_key
left join aliases
    on aliases.raw_source = first_event.source_raw
left join countries
    on countries.country_name = first_event.country_name
