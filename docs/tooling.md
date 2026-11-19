# Tooling

Every tool in this repository, what it does here, how it is used, and why it was chosen over the
obvious alternatives. Modelling choices (how MRR or churn are defined) are in
[decisions.md](decisions.md); this document is about the stack.

Three constraints shaped most of the choices:

1. **Anyone can run it.** `make setup && make data && make build` has to work on a laptop with no
   cloud account and no cost.
2. **It should look like a production stack.** Each tool is the one a subscription business would
   plausibly run, or a local stand-in with a documented path to the production one.
3. **Everything is checked by a machine.** A tool earns its place if CI can run it.

Versions are pinned in [`requirements.txt`](../requirements.txt).

| Layer | Tool | Role |
|---|---|---|
| Source data | Python, NumPy, pandas, PyArrow | Deterministic synthetic generator |
| Storage | Parquet | Raw layer |
| Warehouse | DuckDB (local, CI), Snowflake (target, not run yet) | Where the models are built |
| Transformation | dbt-core, dbt-duckdb, dbt_utils | Models, tests, contracts, docs |
| Metrics | MetricFlow | Semantic layer |
| Orchestration | Dagster, dagster-dbt | Assets, checks, freshness, schedule |
| Code quality | sqlfluff, ruff, pytest | Lint and tests |
| Delivery | Git, GitHub Actions, gh, Make | Branches, CI, local workflow |
| AI | Anthropic API, MCP | Pull-request review, governed analyst access |
| Analysis | Jupyter (nbconvert), SciPy, Matplotlib | Experiment readout |
| Reporting | Python-generated HTML and SVG, GitHub Pages | Published analysis reports |

---

## Source data

### Python 3.11 with NumPy and pandas

**What for.** `generator/generate.py` and `generator/ga4.py` simulate a subscription business day by
day from January 2024 to October 2026: signups, trials, charges, failed payments, churn,
reactivations, a price increase, an A/B test, playback and web sessions.

**How.** One simulator class walks the calendar and appends rows to in-memory lists that become
pandas DataFrames. All randomness comes from seeded `numpy.random.Generator` streams, so the same
seed always produces the same files; new behaviour gets its own stream so existing data does not
shift. `--scale` shrinks the dataset (CI uses 0.2).

**Why this and not something else.**
- *A public dataset* (Kaggle, a vendor sample) has no known ground truth. Here the behaviours are
  planted, so the marts recovering them is an end-to-end test (see "What the data shows" in the
  README), and the source mess (duplicates, mixed-case codes, late events) is deliberate.
- *Faker or SDV* generate plausible rows, not a coherent business: a payment has to follow from a
  subscription, which follows from a signup. That needs a simulation, not a row generator.
- *Real company data* is not an option in a public repository.

### Parquet (PyArrow)

**What for.** The raw layer: ten files in `data/raw/`, one per source table.

**How.** pandas writes most tables; the GA4 export is written with PyArrow directly because its
`event_params` column is a repeated key/value record, the same nested shape as the real BigQuery
export. dbt reads the files in place through `transform/models/staging/_sources.yml`.

**Why this and not something else.**
- *CSV* loses types (timestamps, decimals) and cannot hold nested records, so the GA4 unnesting
  problem would disappear from the project.
- *Loading into a database first* adds a step and a running service. Parquet is what lands in a data
  lake and what Snowflake and BigQuery load natively, so the raw layer looks the same in production.

---

## Warehouse

### DuckDB

**What for.** The warehouse for local development and CI.

**How.** A single file (`data/warehouse.duckdb`, or a temp file in CI). dbt builds one schema per
layer in it. Analysis code (the reconciliation script, the notebook) opens it read-only.

**Why this and not something else.**
- *Snowflake or BigQuery from day one* would put an account, credentials and a bill between a
  reader and `make build`, and CI would spend credits on every push.
- *Postgres* needs a server (or a container) and is row-oriented; six million playback events
  aggregate in seconds in DuckDB and noticeably slower there.
- *SQLite* lacks the analytical SQL the models use (window frames, `unnest`, date functions).

The cost of this choice is that DuckDB is not what a company runs in production. That is handled by
writing warehouse-portable SQL (dbt cross-database macros, one dispatched macro for GA4 unnesting)
and keeping a Snowflake target ready.

### Snowflake (configured, not yet run)

**What for.** The production-style target, and the prerequisite for slim CI with `--defer`.

**How.** A `snowflake` output in `transform/profiles.yml` that takes every credential from
`SNOWFLAKE_*` environment variables. Nothing has been built there yet; the README and
[decisions.md](decisions.md) (9, 11, 21) say what is untested.

**Why this and not something else.** Snowflake is the warehouse most often required for analytics
engineering roles and has a free trial without a card. BigQuery would be the natural home for the
GA4 export, and the staging macro already has a BigQuery variant; running it there is a matter of
adding a profile and contract type names.

---

## Transformation

### dbt-core with dbt-duckdb

**What for.** All transformation, testing and documentation: 33 models in three layers (staging,
intermediate, marts), 3 seeds, 99 data tests, 2 unit tests, contracts on the four public marts.

**How.**
- Staging is one view per source table and does light cleaning only; intermediate holds reusable
  business logic; marts are tables grouped by domain (core, finance, product, marketing,
  experiments). `generate_schema_name` keeps schema names identical on every target.
- Data tests in YAML, five singular tests for reconciliation, and unit tests for the two pieces of
  logic most likely to be wrong (MRR movement classification, attribution).
- One incremental model (`fct_playback_daily`) with a three-day lookback and `delete+insert`.
- Business parameters (as-of date, trial window, constant-FX year) are project `vars`.
- The manifest dbt produces is reused by MetricFlow, Dagster and the PR impact report, so model
  dependencies are declared once.

**Why this and not something else.**
- *SQLMesh* has stronger change planning and virtual environments, but dbt is what hiring teams and
  most data teams run, and the rest of this stack (MetricFlow, dagster-dbt, sqlfluff's dbt
  templater) plugs into dbt's manifest.
- *Dataform* is tied to BigQuery.
- *Plain SQL scripts or pandas* give no dependency graph, no tests next to the model, no contracts
  and no lineage.
- *dbt Cloud* would add a scheduler and the hosted Semantic Layer API, at a price. dbt-core is free
  and the scheduler here is Dagster.

### dbt_utils

**What for.** The date spine behind `dim_date` and the month series, and generic tests such as
unique combinations of columns.

**Why this and not something else.** It is the package nearly every dbt project already depends
on; writing a spine by hand would be reinventing it. It is the only package installed, on purpose:
`dbt_expectations` and similar add many tests but also a dependency to keep compatible, and the
tests needed here are covered by dbt's built-ins plus singular tests.

---

## Metrics

### MetricFlow (dbt-metricflow)

**What for.** The semantic layer: 5 semantic models, 30 metrics and 3 saved queries defined in
`transform/models/semantic/`. Every ratio (churn rates, ARPU, CAC, trial and web conversion) is
defined here once and nowhere else.

**How.**
- Marts store additive measures only; MetricFlow composes ratios at the grain of the question.
- MRR and paying customers are declared semi-additive (`non_additive_dimension`), so a quarter
  takes its closing month instead of summing three months.
- `mf validate-configs` checks the definitions against the warehouse, and
  `scripts/check_semantic_layer.py` compares the `mrr_bridge` saved query with the hand-written
  `rpt_mrr_bridge` mart for every metric and month. Both run in CI.
- The MCP server shells out to the `mf` CLI to answer questions.

**Why this and not something else.**
- *Metrics as columns in the marts* is how ratios end up averaged. A stored churn rate per market
  cannot be rolled up to a region.
- *LookML or a BI tool's own model* (Looker, Power BI, Tableau) locks the definitions inside one
  tool and needs a licence to run.
- *Cube* is a capable open-source alternative, but it is a separate service with its own modelling
  language; MetricFlow definitions live in the dbt project as YAML and move to the dbt Semantic
  Layer unchanged.
- The hosted *dbt Semantic Layer API* is a paid dbt Cloud feature; the open-source CLI is enough to
  prove the definitions are correct.

---

## Orchestration

### Dagster with dagster-dbt

**What for.** Deciding what runs, in what order and whether the data is fresh:
`orchestration/definitions.py` declares 46 assets and 90 asset checks.

**How.**
- The ten raw extracts are one multi-asset that runs the generator; every dbt model is an asset
  loaded from the dbt manifest, grouped by layer and domain.
- Every dbt test becomes an asset check, and the semantic-layer reconciliation is one more check on
  `rpt_mrr_bridge`.
- Raw assets carry a freshness policy (warn after 24 hours, fail after 26).
- The `daily_refresh` job is scheduled at 06:00 UTC. `tests/test_orchestration.py` runs that real
  job end to end on a temporary copy of the repository, in CI.

**Why this and not something else.**
- *Airflow* is the most common orchestrator, but it is organised around tasks. With dbt that means
  either one opaque `dbt build` task or a third-party package (Cosmos) to explode the graph, and it
  needs a database and a scheduler process to run at all. Dagster's unit is the table, which is
  what an analytics engineer is asked about, and it runs from a single `pip install`.
- *Prefect* is lighter than Airflow but also task-first, with no native notion of data assets,
  checks or freshness.
- *cron or a GitHub Actions schedule* would run the build, without lineage, run history, checks as
  first-class objects or freshness.

The split carries over to a team on Airflow: the orchestrator schedules and observes, dbt owns the
transformation graph.

---

## Code quality

### sqlfluff

**What for.** SQL style and a class of real mistakes (ambiguous column references, implicit
aliases) across models, tests and macros.

**How.** Configured in `transform/.sqlfluff` with the dbt templater, so every model is compiled by
dbt before it is linted and Jinja and macros are checked as the warehouse sees them. Three rules
are turned off because they fight dbt conventions; inline `noqa` is used only with a reason.

**Why this and not something else.** *SQLFmt* formats but does not lint, so it would not catch an
ambiguous reference. *Review by eye* spends human attention on commas. sqlfluff is the linter with
a maintained dbt templater.

### ruff

**What for.** Linting and formatting all Python, including the notebook's code cells.

**How.** Configured in `pyproject.toml` (pycodestyle, pyflakes, import order, pyupgrade, bugbear,
and the subprocess-without-`check` rule). `make lint` and CI run `ruff check` and
`ruff format --check`.

**Why this and not something else.** It replaces flake8, isort and black with one fast tool and one
configuration block, and it reads `.ipynb` files natively.

### pytest

**What for.** Everything that is not a dbt test: the Dagster job end to end, the MCP server over
its real stdio protocol, and the experiment statistics (known answers and simulations).

**Why this and not something else.** It is the standard Python test runner; `unittest` would work
with more boilerplate and weaker fixtures. dbt tests cover data and SQL logic, pytest covers the
Python around them.

---

## Delivery

### Git, GitHub and GitHub Actions

**What for.** Version control, a branch and pull request for every change, and CI.

**How.** `.github/workflows/ci.yml` runs three jobs on every pull request: lint; build (generate a
small dataset, `dbt build`, validate and reconcile the semantic layer, pytest, execute the
experiment notebook); and a PR job that posts the impact report and the optional AI review. The
runner image is pinned so it does not change underneath the project.

**Why this and not something else.** The repository is public on GitHub, where Actions is free for
public repositories and needs no extra service. GitLab CI or CircleCI would do the same job with
one more account.

### PR impact report (`scripts/impact_report.py`)

**What for.** Telling a reviewer what a change touches: modified models, everything downstream and
the semantic-layer metrics on top of them.

**How.** CI parses the base branch, then uses dbt's `state:modified+` selection against it and
walks the manifest to the metrics. The result is one PR comment that is updated in place.

**Why this and not something else.** The usual answer is slim CI (`dbt build --select
state:modified+ --defer`), which needs unchanged parents to exist in a persistent warehouse. CI
here starts from an empty DuckDB file and a full build takes about a minute, so CI builds
everything and keeps the part reviewers use. Tools such as Recce or Datafold go further (data
diffs) and are worth adding once there is a production warehouse to diff against.

### gh CLI and Make

**What for.** `gh` creates pull requests and posts the CI comment. The `Makefile` is the local
interface: `setup`, `data`, `build`, `metrics`, `orchestrate`, `lint`, `readout`.

**Why this and not something else.** Make is already on every macOS and Linux machine and documents
the commands in one file. Task runners such as `just` or `invoke` are nicer to write and one more
thing to install.

---

## AI

### Anthropic API (pull-request review)

**What for.** A second reviewer on every pull request, focused on what tests cannot fully cover:
grain, metric definitions, snapshot versus flow, currency handling.

**How.** `scripts/ai_review.py` sends the diff and the impact report with
`docs/review_guidelines.md` as the standard to review against, and posts findings with file, line
and severity. It runs only when the repository has an `ANTHROPIC_API_KEY` secret, it never blocks a
merge (`continue-on-error`), and `--dry-run` prints the exact prompt so the same review can be run
in an interactive assistant at no cost. The secret is not set today, so the step is skipped.

**Why this and not something else.** Hosted review bots apply generic rules; the value here is the
written guideline specific to this project's definitions. Keeping it opt-in and non-blocking is the
point of [decision 22](decisions.md): the review informs, the tests decide.

### Model Context Protocol (MCP server)

**What for.** Letting an AI analyst answer business questions from governed metrics.

**How.** `semantic_agent/` exposes four read-only tools over stdio: `list_metrics`,
`describe_metric`, `query_metrics` (rows plus the SQL MetricFlow generated) and `verify_number`,
which re-derives a number through an independent path before it is reported. `.mcp.json` registers
the server when the repository is opened in an MCP client. There is no tool that runs arbitrary
SQL.

**Why this and not something else.**
- *Text-to-SQL over the warehouse* will eventually sum a snapshot or join at the wrong grain, and
  the answer looks just as confident. Restricting the agent to the semantic layer keeps the
  definitions with the data team.
- *A custom chat application* would need a UI, hosting and an API bill. MCP makes the same server
  usable from any compatible client with that client's own model.
- *The dbt Semantic Layer's hosted integrations* require dbt Cloud.

---

## Analysis

### Jupyter (executed with nbconvert), SciPy and Matplotlib

**What for.** The readout of the paywall A/B test in
`notebooks/paywall_experiment_readout.ipynb`.

**How.**
- The statistics (intervals, power, CUPED, sample-ratio test) are plain functions in
  `analysis/experiment.py` built on SciPy's distributions, with unit tests. The notebook imports
  them and adds narrative and charts.
- The notebook reads the marts from DuckDB read-only and is committed with its outputs, so it
  renders on GitHub without running anything.
- CI executes it with `nbconvert` against the freshly built warehouse, so a mart change that breaks
  the analysis fails the build. `make readout` re-runs it locally.

**Why this and not something else.**
- *A notebook with the statistics inline* cannot be unit tested and rots quietly.
- *statsmodels* has ready-made power and proportion functions; the formulas needed here are a few
  lines each, and writing them out keeps the assumptions visible and testable.
- *A BI dashboard* suits monitoring a metric, not a one-off decision that needs a stated rule,
  intervals and caveats in prose.
- *Marimo or Quarto* are good reproducible alternatives; `.ipynb` is the format GitHub renders
  inline and most analysts already open.
- *Plotly* would add interactivity that a static GitHub rendering does not show.

---

## Reporting

### Generated HTML with inline SVG, published with GitHub Pages

**What for.** Five static pages with the main results (overview, revenue, retention, acquisition,
experiment), readable without cloning the repository:
<https://jonatefrias.github.io/subscription-analytics-platform/>.

**How.**
- `reports/build.py` queries the warehouse and writes the pages. MRR, churn, ARPU, CAC and the
  conversion rates go through MetricFlow, using the same wrapper as the MCP server; cohorts,
  attribution and the experiment read the marts. Headlines and prose interpolate the numbers.
- `reports/charts.py` draws the charts as inline SVG (lines, stacked and grouped bars, heatmap,
  intervals) with CSS variables for light and dark mode and a small script for hover tooltips.
- CI builds the pages on every pull request. `.github/workflows/pages.yml` rebuilds them on the
  default dataset and deploys them on every merge to `main`. The output (`site/`) is not committed.

**Why this and not something else.**
- *Hand-written HTML pages* would drift from the models at the first change; generated pages cannot.
- *A BI tool or a Streamlit/Evidence app* needs a server or a hosted account to be seen. Static
  files on GitHub Pages cost nothing and have nothing to keep running.
- *Plotly, Vega or another charting library* would give more chart types and richer interaction,
  at the price of a JavaScript dependency loaded from a CDN or bundled into every page. A few
  hundred lines of SVG cover the five chart types the reports need.
- *Publishing the notebook as HTML* (nbconvert, Quarto) shows the method; these pages are the
  short version for a reader who wants the result.
- *dbt docs* answers a different question (lineage and column documentation) and is still a good
  candidate to publish next to the reports.

---

## Deliberately not here

| Missing | Why |
|---|---|
| A BI tool (Looker, Power BI, Tableau, Metabase) | A dashboard would need hosting or a licence to be seen. The static reports cover the reading; the semantic layer is what a BI tool would sit on. |
| An ingestion tool (Fivetran, Airbyte, dlt) | There is no external system to extract from; the generator plays that role and the staging layer handles the source quirks an extractor would deliver. |
| Docker | One `pip install` into a virtualenv reproduces the environment; a container would add a prerequisite without removing one. |
| Streaming (Kafka, Flink) | The business questions are daily and monthly. Late and duplicated events are handled in batch with a lookback window. |
| A data observability product | dbt tests, Dagster asset checks and freshness policies cover what the project needs at this size. |
