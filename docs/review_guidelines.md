# Review guidelines

What a reviewer (human or the AI reviewer in CI) checks on every pull request. Style is not on
the list: sqlfluff and ruff enforce it. A finding needs evidence in the diff: a file, a line,
and a concrete way it produces a wrong number, a broken run or a misleading definition.

## 1. Numbers stay correct
- **Grain.** Every model states its grain (one row per ...). A join that can fan out the grain
  (one-to-many on a fact) needs a test that proves it does not, e.g. `unique_combination_of_columns`.
- **Snapshots vs flows.** Balances (MRR, paying customers) are never summed over time. In the
  semantic layer they carry `non_additive_dimension`; flows (new, churned) stay additive.
- **Ratios live in the semantic layer.** Marts hold additive facts; a ratio stored as a column
  will be averaged by someone.
- **Currency.** MRR uses constant FX; revenue uses the FX of the billing day. Never mix them.
- **Time.** Dates come from UTC timestamps. GA4's `event_date` (property time zone) is not used.
- **Sources of truth.** Signups and revenue come from CRM and billing, never from GA4.
- **Null handling.** A filtered metric must return 0, not null, when nothing matches
  (`fill_nulls_with: 0`); a division must guard against zero.

## 2. Every change is tested
- A new model has at least: primary key `unique` + `not_null`, and `accepted_values` on any
  categorical column used for filtering.
- New business logic with branches (classification, attribution, lifecycle) gets a dbt unit test.
- A public mart (`dim_*`, `fct_*` used by BI) has an enforced contract; changing its columns
  is a breaking change and must say so in the PR description.
- A new metric that overlaps a mart number is covered by `scripts/check_semantic_layer.py`.

## 3. The project stays portable and reproducible
- Cross-database macros (`dbt.dateadd`, `dbt.datediff`, `dbt.date_trunc`) instead of vendor
  syntax; vendor-specific code goes behind `adapter.dispatch`.
- The generator stays deterministic: a change must not alter existing tables unless that is
  the point of the change (new random draws go on their own random stream).
- No credentials, personal data or real company data in the repo.

## 4. Decisions are written down
- A change in a definition (MRR, churn, attribution, sessions) updates `docs/decisions.md`
  with the alternative that was rejected.
- README numbers that the change moves are updated.

## Severity
- **Blocker**: produces wrong numbers, breaks the build or a contract, leaks data.
- **Should fix**: missing test or doc for new logic, a definition that will confuse users.
- **Question**: something that looks wrong but may be intended; ask instead of asserting.
