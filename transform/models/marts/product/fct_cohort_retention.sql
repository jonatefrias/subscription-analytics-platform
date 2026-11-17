-- sqlfluff:max_line_length:220
-- (dbt.datediff renders onto one long line; the source lines are short)
-- Paying-customer retention by first-paid cohort (month) and months since first payment.
with paying as (

    select
        customer_id,
        month_start
    from {{ ref('fct_mrr_monthly') }}
    where mrr_usd > 0

),

cohorts as (

    select
        customer_id,
        min(month_start) as cohort_month
    from paying
    group by 1

),

cohort_sizes as (

    select
        cohort_month,
        count(*) as cohort_customers
    from cohorts
    group by 1

)

select
    cohorts.cohort_month,
    {{ dbt.datediff('cohorts.cohort_month', 'paying.month_start', 'month') }} as months_since_first_paid,
    cohort_sizes.cohort_customers,
    count(*) as retained_customers,
    cast(count(*) as numeric(18, 6)) / cohort_sizes.cohort_customers as retention_rate
from paying
inner join cohorts
    on cohorts.customer_id = paying.customer_id
inner join cohort_sizes
    on cohort_sizes.cohort_month = cohorts.cohort_month
group by 1, 2, 3
