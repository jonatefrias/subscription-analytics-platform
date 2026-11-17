{{ config(severity='warn') }}
-- GA4 should see at least 80% of web signups. Below that, something changed in tagging or
-- consent, and GA4-based conversion rates are no longer comparable month to month.
select
    signup_month,
    crm_web_signups,
    ga4_signups,
    tracking_coverage
from {{ ref('rpt_web_tracking_coverage') }}
where tracking_coverage < 0.80
    and crm_web_signups >= 50
