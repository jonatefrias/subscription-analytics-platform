-- Customer x month MRR with the movement that explains the change versus the prior month.
-- The grid is dense from each customer's first paying month, so churn months exist as rows.
with months as (

    select month_start from {{ ref('int_months') }}

),

customer_months as (

    select
        customer_id,
        month_start,
        mrr_usd
    from {{ ref('int_mrr__customer_months') }}

),

first_month as (

    select
        customer_id,
        min(month_start) as first_month
    from customer_months
    group by 1

),

grid as (

    select
        first_month.customer_id,
        months.month_start
    from first_month
    inner join months
        on months.month_start >= first_month.first_month

),

filled as (

    select
        grid.customer_id,
        grid.month_start,
        coalesce(customer_months.mrr_usd, 0) as mrr_usd
    from grid
    left join customer_months
        on customer_months.customer_id = grid.customer_id
            and customer_months.month_start = grid.month_start

),

with_history as (

    select
        *,
        coalesce(lag(mrr_usd) over (partition by customer_id order by month_start), 0) as previous_mrr_usd,
        coalesce(max(mrr_usd) over (
            partition by customer_id order by month_start
            rows between unbounded preceding and 1 preceding
        ), 0) as max_prior_mrr_usd
    from filled

),

classified as (

    select
        *,
        case
            when previous_mrr_usd = 0 and mrr_usd > 0 and max_prior_mrr_usd = 0 then 'new'
            when previous_mrr_usd = 0 and mrr_usd > 0 then 'reactivation'
            when previous_mrr_usd > 0 and mrr_usd = 0 then 'churn'
            when mrr_usd > previous_mrr_usd then 'expansion'
            when mrr_usd < previous_mrr_usd then 'contraction'
            when mrr_usd > 0 then 'retained'
            else 'inactive'
        end as movement_type
    from with_history

)

select
    cast(customer_id as varchar) as customer_id,
    cast(month_start as date) as month_start,
    cast(previous_mrr_usd as numeric(18, 4)) as previous_mrr_usd,
    cast(mrr_usd as numeric(18, 4)) as mrr_usd,
    cast(mrr_usd - previous_mrr_usd as numeric(18, 4)) as mrr_change_usd,
    cast(movement_type as varchar) as movement_type
from classified
where movement_type <> 'inactive'
