-- The playback stream is at-least-once: drop repeated event ids, parse the ISO
-- timestamps and discard events with invalid watch time (negative or missing).
with source as (

    select * from {{ source('raw', 'app_playback_events') }}

),

deduplicated as (

    select
        *,
        row_number() over (partition by event_id order by played_at) as delivery_rank
    from source

)

select
    event_id,
    customer_id,
    content_id,
    content_type,
    cast(replace(replace(played_at, 'T', ' '), 'Z', '') as timestamp) as played_at,
    cast(watch_seconds as integer)                                   as watch_seconds
from deduplicated
where delivery_rank = 1
  and watch_seconds >= 0
