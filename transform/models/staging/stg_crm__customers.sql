-- One row per customer: keep the latest profile version from the CRM export
-- and normalise the fields the export gets wrong.
with source as (

    select * from {{ source('raw', 'crm_customers') }}

),

ranked as (

    select
        *,
        row_number() over (partition by customer_id order by updated_at desc) as version_rank
    from source

)

select
    customer_id,
    cast(created_at as timestamp) as created_at,
    upper(trim(country)) as country_code,
    lower(signup_platform) as signup_platform,
    coalesce(acquisition_channel, 'unknown') as acquisition_channel,
    cast(updated_at as timestamp) as profile_updated_at
from ranked
where version_rank = 1
