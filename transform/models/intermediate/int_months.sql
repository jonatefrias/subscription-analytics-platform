-- Reporting month spine: from the first reporting month up to the month before as_of_date.
with spine as (

    {{ dbt_utils.date_spine(
        datepart="month",
        start_date="cast('" ~ var('reporting_start_month') ~ "' as date)",
        end_date=as_of_date()
    ) }}

)

select
    cast(date_month as date)                                           as month_start,
    cast({{ dbt.dateadd('month', 1, 'date_month') }} as timestamp)     as snapshot_at
from spine
