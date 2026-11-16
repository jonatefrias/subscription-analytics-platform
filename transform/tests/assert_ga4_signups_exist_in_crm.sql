-- Every user_id GA4 saw on a sign_up must exist in the CRM. A miss means the web app is
-- sending an id the backend does not know (test accounts, a changed id format, ...).
select distinct events.user_id
from {{ ref('stg_ga4__events') }} as events
left join {{ ref('dim_customers') }} as customers
    on customers.customer_id = events.user_id
where events.event_name = 'sign_up'
  and customers.customer_id is null
