-- One row per GA4 event with the parameters we use pulled out of the repeated record.
-- Dates are derived from the UTC timestamp: the export's event_date is the property's
-- local day (New York), which would put late-evening events on the wrong day.
with source as (

    select * from {{ source('raw', 'ga4_events') }}

),

flattened as (

    select
        {{ micros_to_timestamp('event_timestamp') }} as event_at,
        event_timestamp,
        event_date as property_date_key,
        event_name,
        user_pseudo_id,
        user_id,
        cast({{ ga4_param('event_params', 'ga_session_id', 'int_value') }} as bigint) as ga_session_id,
        cast({{ ga4_param('event_params', 'ga_session_number', 'int_value') }} as integer) as ga_session_number,
        {{ ga4_param('event_params', 'page_location', 'string_value') }} as page_location,
        cast({{ ga4_param('event_params', 'engagement_time_msec', 'int_value') }} as bigint) as engagement_time_msec,
        {{ ga4_param('event_params', 'plan_id', 'string_value') }} as plan_id,
        {{ ga4_param('event_params', 'transaction_id', 'string_value') }} as transaction_id,
        cast({{ ga4_param('event_params', 'value', 'double_value') }} as numeric(18, 4)) as purchase_value,
        {{ ga4_param('event_params', 'currency', 'string_value') }} as purchase_currency,
        -- device, geo and collected_traffic_source are structs; sqlfluff reads struct.field as table.column
        -- noqa: disable=RF01
        device.category as device_category,
        device.operating_system as operating_system,  -- noqa: AL09
        geo.country as country_name,
        nullif(lower(trim(collected_traffic_source.manual_source)), '') as source_raw,
        nullif(replace(lower(trim(collected_traffic_source.manual_medium)), '-', '_'), '') as medium,
        collected_traffic_source.manual_campaign_name as campaign,
        collected_traffic_source.gclid
        -- noqa: enable=RF01
    from source

)

select
    {{ dbt_utils.generate_surrogate_key(['user_pseudo_id', 'event_timestamp', 'event_name']) }} as event_key,
    user_pseudo_id || '-' || cast(ga_session_id as varchar) as session_key,
    *
from flattened
