-- GA4 web sessions with the customer they belong to, when known.
-- customer_id comes from identity stitching, so it is also filled for the anonymous
-- sessions a cookie had before the person signed up.
with sessions as (

    select * from {{ ref('int_ga4__sessions') }}
    where session_started_at < {{ as_of_ts() }}

),

identity as (

    select * from {{ ref('int_ga4__identity_map') }}

)

select
    sessions.session_key,
    sessions.user_pseudo_id,
    identity.customer_id,
    sessions.session_user_id is null and identity.customer_id is not null  as is_identified_by_stitching,
    sessions.session_started_at,
    cast(sessions.session_started_at as date)                             as session_date,
    sessions.ga_session_number,
    sessions.device_category,
    sessions.market_code,
    sessions.source,
    sessions.medium,
    sessions.campaign,
    sessions.channel,
    sessions.page_views,
    sessions.engagement_seconds,
    sessions.is_engaged,
    sessions.reached_paywall,
    sessions.selected_plan,
    sessions.signed_up,
    sessions.started_trial,
    sessions.purchased,
    sessions.logged_in,
    cast(sessions.purchase_value as numeric(18, 4))                       as purchase_value_local
from sessions
left join identity
    on identity.user_pseudo_id = sessions.user_pseudo_id
