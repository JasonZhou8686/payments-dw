# CLAUDE.md — conventions for the payments-dw dbt project

This file is read by the coding agent at the start of every session. It is the single source of
truth for how this project is built. Humans follow it too.

## Stack

- Warehouse: Google BigQuery, location `US`. Raw data lands in dataset `raw`.
- Transformation: dbt Core with `dbt-bigquery`. Dev target writes to `dbt_jason`, CI to `dbt_ci`.
- Packages: `dbt_utils`, `dbt_expectations` (see `packages.yml`). Run `dbt deps` after cloning.
- Python 3.11 in `.venv`. Activate it before any `dbt` or `python` command.
- Credentials: `~/.dbt/profiles.yml` and `~/.gcp/*.json`. Never read, print, copy or commit them.

## Layering (strict)

| Layer        | Folder                 | Prefix | Materialization                      | Rules |
|--------------|------------------------|--------|--------------------------------------|-------|
| staging      | `models/staging/<src>` | `stg_` | view                                 | 1:1 with a raw table. Rename, cast, light cleanup only. No joins. No business logic. |
| intermediate | `models/intermediate`  | `int_` | view (ephemeral if only used once)   | Joins and reusable business logic. Never queried by BI. |
| marts        | `models/marts`         | `fct_` / `dim_` | table; facts are incremental + partitioned | What analysts and ML read. |

- Staging models select from `{{ source('payments', '<table>') }}` only. Everything else uses `{{ ref() }}`.
- Never reference a `raw.*` table outside staging.
- One model per file; file name == model name.

## Naming

- Snake case everywhere. Columns: `<entity>_id`, `<thing>_at` for timestamps (UTC), `<thing>_date` for dates,
  `is_<flag>` for booleans, `amount_cents` for money stored as integers, `amount` for NUMERIC dollars.
- Money: raw tables store cents as INT64. Staging converts to NUMERIC dollars via `{{ cents_to_dollars('col') }}`
  and keeps the `_cents` column too.
- Primary key of every model is the first column and is named `<model_entity>_id` (e.g. `transaction_id`).

## SQL style

- Lowercase keywords, 4-space indent, leading commas, CTEs over subqueries.
- Every model starts with `with source as (select * from ...)` → `renamed as (...)` → `select * from renamed`
  for staging; `with` CTEs named by what they contain for other layers.
- Never `select *` from a `ref()`/`source()` in marts; list columns.
- Incremental facts: `materialized='incremental'`, `incremental_strategy='insert_overwrite'`,
  `partition_by={'field': '<date col>', 'data_type': 'date'}`, `cluster_by=['merchant_id']`, and an
  `{% if is_incremental() %}` filter on the partition column.
- Use `safe_cast` when casting raw strings. Use `qualify` for dedup instead of a subquery.

## Tests and docs (required for every model)

Every model has an entry in the folder's `_<layer>__models.yml` with:
- `description` on the model and on every column.
- Primary key: `unique` + `not_null`.
- Foreign keys: `relationships` to the parent `dim_`/`stg_` model.
- Enum columns: `accepted_values`.
- Money columns: `dbt_expectations.expect_column_values_to_be_between` with `min_value: 0`
  unless negatives are valid (refunds). Say so in the description.
- At least one business-rule test per fact (singular test in `tests/` or `dbt_utils.expression_is_true`).

Sources are declared in `models/staging/<src>/_<src>__sources.yml` with `loaded_at_field` and freshness.

## Workflow the agent must follow

1. Read this file and the relevant `_*.yml` before writing any model.
2. Before creating a staging model, inspect the raw schema:
   `bq show --schema --format=prettyjson $GCP_PROJECT:raw.<table>` (or ask the user to paste it).
3. Write the SQL and the YAML entry together — a model without YAML is not done.
4. Run `dbt build --select <model>+` (the `+` runs downstream too) and fix failures before reporting back.
5. Keep changes small; one model (plus its YAML/tests) per commit.
6. Never run `dbt build` with no selector against `prod`. Never drop datasets.
7. If a spec exists in `specs/` for what you are building, treat it as the requirements; ask if it is ambiguous.

## Things to never do

- No `select *` in marts. No hard-coded project IDs or dataset names (use `target.project`/`target.schema`).
- No transformations in Python that belong in dbt.
- No credentials in code, logs, comments or commits.
- Don't modify `dbt_project.yml` materialization defaults without asking.
