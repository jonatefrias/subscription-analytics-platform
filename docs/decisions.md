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

## 10. Dates come from the UTC timestamp, not from GA4's `event_date`
The GA4 export's `event_date` is the *property's* local day (New York here), while billing and
playback are in UTC. Using `event_date` would move evening sessions to the next day and break
day-level joins with spend and signups. Every web date is derived from `event_timestamp`.

## 11. One macro per warehouse for GA4 parameters
`event_params` is a repeated key/value record, and DuckDB, BigQuery and Snowflake unnest it with
different syntax. `ga4_param()` dispatches per adapter, so the staging model reads the same on
every warehouse. Only the DuckDB variant runs in CI; the BigQuery and Snowflake variants are untested.

## 12. GA4 is never the source of truth for signups
About 12% of visitors decline analytics consent and some sign up on a device GA4 never linked.
Signup and revenue counts come from the CRM and billing. GA4 explains *how* people arrived, and
`rpt_web_tracking_coverage` measures how much of the business it sees, with a warn-level test
when coverage drops below 80%.

## 13. Two attribution views side by side, no blended model
First touch and last non-direct are both kept, next to the channel the CRM recorded. They
answer different questions (what opens the door vs what closes the deal), and the gap between
them is the finding: retargeting makes last-touch over-credit paid social. A data-driven or
position-based model would need more signal than a portfolio dataset can justify.
