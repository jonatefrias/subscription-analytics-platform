# Design decisions

Short records of the choices that shape the models, with the alternative that was rejected.

## 1. MRR is a month-end snapshot, not a sum of invoices
Summing invoices per month makes annual plans spike once a year and makes failed-then-retried
charges move revenue between months. A snapshot of *active paying subscriptions at the first
instant of the next month* is stable and is what a subscription business plans against.
Invoices still drive cash and revenue reporting in `fct_payments`.

## 2. Constant FX for MRR, daily FX for revenue
The business bills in six currencies. At daily FX, a 5% move in the peso shows up as MRR
contraction even if no customer changed anything. MRR therefore uses the average rate of a
budget year (`var('constant_fx_year')`). `fct_payments` keeps both amounts, so finance can
reconcile to actuals.

## 3. List price as-of the snapshot (SCD2), not the last charge
MRR is priced from the plan price list in force on the last day of the month. A price change
then appears as expansion in the month it takes effect, which is exactly what leadership wants
to see after a price increase.

## 4. Churn happens when access ends
A cancellation does not remove MRR until the paid period ends. The bridge reflects revenue the
company will no longer collect, not intent. Cancellation timing is still available in
`fct_subscriptions.canceled_at` for retention work.

## 5. Plan switches are not reactivations
A monthly → annual switch ends one subscription and starts another on the same day. The
successor is flagged `is_plan_change`, so it is not counted as a reactivation.

## 6. Facts hold additive measures only
`fct_acquisition_daily` stores signups, conversions and spend, never CAC or conversion rates.
Ratios of sums must be computed at the grain of the question. That job belongs to the metrics
layer (next milestone), not to pre-aggregated columns that someone will average.

## 7. Incremental playback with a lookback
Playback events arrive late (offline viewing, client retries). The incremental model reprocesses
the last three days on every run with `delete+insert`, which keeps it idempotent.

## 8. Contracts only where people depend on the shape
Contracts are enforced on the four public marts consumed by BI. Staging and intermediate
models change often and are protected by tests instead.

## 9. DuckDB first, warehouse-portable SQL
Cross-database macros (`dbt.dateadd`, `dbt.datediff`, `dbt.date_trunc`) and no vendor-specific
syntax keep the project portable to Snowflake. One caveat: the contract data types are declared
in DuckDB/Snowflake names, so BigQuery would need its own type names.
