-- One row per subscription with everything needed to place it in a customer's lifecycle:
-- when it started paying, whether it is a reactivation, and its status at the cut-off.
with subscriptions as (

    select * from {{ ref('stg_billing__subscriptions') }}

),

plans as (

    select * from {{ ref('stg_billing__plans') }}

),

successful_charges as (

    select
        subscription_id,
        min(period_start)                                as first_paid_period_start,
        count(*)                                         as paid_charges,
        sum(amount_usd)                                  as gross_revenue_usd,
        sum(case when is_refunded then amount_usd else 0 end) as refunded_usd
    from {{ ref('int_payments__converted') }}
    where payment_status = 'paid'
    group by 1

),

sequenced as (

    select
        subscriptions.*,
        row_number() over (
            partition by subscriptions.customer_id
            order by subscriptions.started_at, subscriptions.subscription_id
        )                                                                         as subscription_number,
        lag(subscriptions.cancel_reason) over (
            partition by subscriptions.customer_id
            order by subscriptions.started_at, subscriptions.subscription_id
        )                                                                         as previous_cancel_reason
    from subscriptions

)

select
    sequenced.subscription_id,
    sequenced.customer_id,
    sequenced.plan_id,
    plans.market_code,
    plans.billing_period,
    plans.months_per_period,
    sequenced.payment_provider,
    sequenced.started_at,
    sequenced.trial_end_at,
    sequenced.canceled_at,
    sequenced.ended_at,
    sequenced.cancel_reason,
    sequenced.subscription_number,
    sequenced.trial_end_at is not null                                            as had_trial,
    charges.first_paid_period_start is not null                                   as has_paid,
    cast(charges.first_paid_period_start as timestamp)                            as paid_from,
    coalesce(charges.paid_charges, 0)                                             as paid_charges,
    coalesce(charges.gross_revenue_usd, 0)                                        as gross_revenue_usd,
    coalesce(charges.refunded_usd, 0)                                             as refunded_usd,
    sequenced.subscription_number > 1
        and coalesce(sequenced.previous_cancel_reason, '') <> 'plan_change'       as is_reactivation,
    coalesce(sequenced.previous_cancel_reason, '') = 'plan_change'                as is_plan_change,
    case
        when sequenced.ended_at <= {{ as_of_ts() }}           then 'ended'
        when sequenced.canceled_at is not null                then 'non_renewing'
        when sequenced.trial_end_at > {{ as_of_ts() }}        then 'trialing'
        else 'active'
    end                                                                           as status_as_of
from sequenced
inner join plans
    on plans.plan_id = sequenced.plan_id
left join successful_charges as charges
    on charges.subscription_id = sequenced.subscription_id
