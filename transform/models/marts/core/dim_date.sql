with spine as (

    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('" ~ var('reporting_start_month') ~ "' as date)",
        end_date=as_of_date()
    ) }}

)

select
    cast(spine.date_day as date) as date_day,
    cast({{ dbt.date_trunc('month', 'spine.date_day') }} as date) as month_start,
    extract(year from spine.date_day) as calendar_year,
    extract(isodow from spine.date_day) as iso_weekday,
    extract(isodow from spine.date_day) in (6, 7) as is_weekend,
    extract(month from spine.date_day) in (6, 7) as is_off_season,
    matches.match_date is not null as is_big_match_day,
    matches.event_name as big_match_name
from spine
left join {{ ref('big_match_days') }} as matches
    on matches.match_date = cast(spine.date_day as date)
