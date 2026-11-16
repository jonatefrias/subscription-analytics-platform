-- Cookie -> customer. GA4 only carries user_id after sign_up or login, so a cookie is
-- linked to the first customer it was ever seen with. That retroactively identifies the
-- anonymous sessions the same cookie had before signing up.
-- Cookies seen with more than one customer (shared devices) keep the first one and are flagged.
with identified as (

    select
        user_pseudo_id,
        user_id,
        event_at,
        row_number() over (partition by user_pseudo_id order by event_at) as seen_rank,
        count(distinct user_id) over (partition by user_pseudo_id)       as customers_on_cookie
    from {{ ref('stg_ga4__events') }}
    where user_id is not null

)

select
    user_pseudo_id,
    user_id                         as customer_id,
    event_at                        as first_identified_at,
    customers_on_cookie > 1         as is_shared_cookie
from identified
where seen_rank = 1
