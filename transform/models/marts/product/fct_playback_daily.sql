{{
    config(
        materialized='incremental',
        unique_key=['customer_id', 'activity_date'],
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns'
    )
}}
-- Customer x day engagement. Incremental with a 3-day lookback because playback
-- events arrive late (offline mobile playback, client retries).
select
    customer_id,
    cast(played_at as date)                                                      as activity_date,
    count(*)                                                                     as plays,
    count(distinct content_id)                                                   as distinct_content,
    cast(sum(watch_seconds) / 60.0 as numeric(18, 2))                            as watch_minutes,
    cast(sum(case when content_type = 'live' then watch_seconds else 0 end) / 60.0 as numeric(18, 2)) as live_minutes
from {{ ref('stg_app__playback_events') }}
where played_at < {{ as_of_ts() }}
{% if is_incremental() %}
  and cast(played_at as date) >= (select {{ dbt.dateadd('day', -3, 'max(activity_date)') }} from {{ this }})
{% endif %}
group by 1, 2
