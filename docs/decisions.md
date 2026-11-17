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

## 14. Snapshot measures are declared non-additive
MRR, paying customers and their opening values are balances, not flows. Summing them over the
months of a quarter triples the number. In the semantic layer they carry a `non_additive_dimension`
on the month: closing values take the last month of the period (`window_choice: max`) and opening
values the first (`min`). Flows such as new or churned MRR stay additive. A quarterly check in CI
proves the rule.

## 15. The metric layer has to reconcile with the marts
A metric definition is code that can be wrong (a filter on the wrong value, a missing
`fill_nulls_with`). `scripts/check_semantic_layer.py` queries the `mrr_bridge` saved query and
compares every metric, every month, with `rpt_mrr_bridge`. On its first run it caught that filtered
metrics returned null instead of 0 in months without that movement, which also nulled the gross
MRR churn rate. Hence `fill_nulls_with: 0` on every flow metric.

## 16. Semantic layer runs locally with MetricFlow, not dbt Cloud
The dbt Semantic Layer API (JDBC/GraphQL for BI tools) is a paid dbt Cloud feature. The
definitions here are standard dbt YAML, so they would work there unchanged; locally they are
validated and queried with the open-source `mf` CLI, which is enough to prove they are correct.

## 17. Dagster with software-defined assets, not a task DAG
The unit of work is the table, not the task. Each raw extract and each dbt model is an asset, so
lineage, run history and data checks hang off the thing people care about. dagster-dbt reads the
dbt manifest, so dbt stays the single source of model dependencies; nothing is declared twice.
Every dbt test shows up as an asset check, and the semantic-layer reconciliation is one more check
on `rpt_mrr_bridge`. In a team that already runs Airflow, the same split applies: the
orchestrator schedules and observes, dbt owns the transformation graph.

## 18. Freshness is a policy on the raw assets
Raw extracts carry a freshness policy: warn after 24 hours without a refresh, fail after 26. That
is the contract with the ingestion side. Downstream models inherit staleness through lineage, so
they do not need their own policies.

## 19. The orchestration is tested end to end, in isolation
`tests/test_orchestration.py` copies the repo to a temp folder, points `PROJECT_ROOT` and the
warehouse there, and runs the real `daily_refresh` job: generator, `dbt build`, every asset check.
It proves the scheduled job works as a whole without touching local data, and it runs in CI.

## 20. The linter owns style, so reviews do not
sqlfluff renders every model through dbt before linting, so Jinja and macros are checked as
the warehouse will see them; ruff covers the Python. Three rules are off because they fight
common dbt conventions (column order in selects, table order in joins, `select *` in import
CTEs). Inline `noqa` is used only where the rule is wrong for the code, with a comment saying why.

## 21. Impact report instead of slim CI, until there is a production warehouse
Slim CI (`dbt build --select state:modified+ --defer`) needs the unchanged parents to exist in a
persistent warehouse; CI here uses a fresh DuckDB file, and a full build takes about a minute. So
CI builds everything, and each pull request gets an impact report from the same state comparison:
changed models, everything downstream, and the semantic-layer metrics on top of them. That is the
part reviewers use; the `--defer` build switches on with the Snowflake target.

## 22. AI review is a second pair of eyes, never a gate
`scripts/ai_review.py` sends the diff and the impact report to Claude with
`docs/review_guidelines.md` and posts findings with file, line and severity. It focuses on what
tests cannot fully cover: grain, definitions, snapshot vs flow, currency. It runs only when the
repository has an `ANTHROPIC_API_KEY` secret (otherwise CI costs nothing), it never blocks a
merge (`continue-on-error`), and `--dry-run` prints the exact prompt so the same review can be
run for free in an interactive assistant.
