-- A customer cannot carry MRR in a month unless they have at least one successful charge
-- on or before that month.
select
    mrr.customer_id,
    mrr.month_start
from {{ ref('fct_mrr_monthly') }} as mrr
where mrr.mrr_usd > 0
    and not exists (
        select 1
        from {{ ref('fct_payments') }} as payments
        where payments.customer_id = mrr.customer_id
            and payments.payment_status = 'paid'
            and payments.period_start < {{ dbt.dateadd('month', 1, 'mrr.month_start') }}
    )
