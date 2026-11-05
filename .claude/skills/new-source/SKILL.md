---
name: new-source
description: Scaffold a dbt staging model for a raw BigQuery table — inspects the schema, writes stg_<src>__<table>.sql and its YAML with tests, then builds it. Use when asked to "add a staging model", "stage <table>", or "/new-source <table>".
---

# /new-source <table>

Create a complete, tested staging model for one raw table, following `CLAUDE.md` exactly.

## Inputs
- `table`: the raw table name (e.g. `transactions`). Source name is `payments`, dataset `raw`.

## Steps

1. **Inspect the real schema.** Run:
   `bq show --schema --format=prettyjson $GCP_PROJECT:raw.<table>`
   If `bq` is unavailable, query the schema through dbt instead:
   `dbt show --inline "select column_name, data_type, is_nullable from {{ target.project }}.raw.INFORMATION_SCHEMA.COLUMNS where table_name = '<table>' order by ordinal_position" --limit 50`
   Never guess column names. Don't use the schema's `is_nullable` to decide on `not_null` tests: `NULLABLE`
   is the BigQuery loader default and says nothing about the data (see step 4).

2. **Check the source entry.** Ensure `models/staging/payments/_payments__sources.yml` lists the table. Add it if missing,
   with `loaded_at_field` set to its timestamp column.

3. **Write `models/staging/payments/stg_payments__<table>.sql`** using the `source` → `renamed` → `select *` CTE pattern:
   - Keep every raw column, in the raw order, with the primary key first.
   - Cast with `safe_cast` where the raw type is STRING but the name implies a number/date/timestamp.
   - For every `*_cents` INT64 column, add `{{ cents_to_dollars('<col>') }} as <col without _cents>` right after it.
   - For nested STRUCTs, flatten the fields you expect analysts to filter on (e.g. `card.brand as card_brand`)
     **and** keep the original struct column. Do not UNNEST repeated fields in staging — that changes the grain.
   - Add `date(<created timestamp>) as <entity>_date` if the table has a creation timestamp.
   - No joins, no filters, no business logic.

4. **Write the YAML entry** in `models/staging/payments/_payments__models.yml`:
   - Model `description`; `description` on every column.
   - PK: `unique` + `not_null`. Enum columns: `accepted_values` — derive the values by running
     `bq query --nouse_legacy_sql 'select distinct <col> from raw.<table>'`.
   - Money columns: `dbt_expectations.expect_column_values_to_be_between` with `min_value: 0`.
   - FK columns (`merchant_id`, `transaction_id`): `relationships` to the matching staging model if it exists.
   - `not_null`: decide from what the column means plus the observed null count, not from the schema mode.
     Add it to FKs, creation/event timestamps and dates, and any column that must always be present, when the
     data has zero nulls. Skip it on columns that are null by design (e.g. `resolved_at` while unresolved) and
     say so in the description. If a must-have column has nulls today, report it instead of adding a failing test.

5. **Build and verify.** `dbt build --select stg_payments__<table>`. Fix any failure. Then run
   `dbt show --select stg_payments__<table> --limit 5` and sanity-check the output.

6. **Report** in ≤6 lines: file(s) created, row count, tests passed, anything you were unsure about.

## Do not
- Do not touch other models. Do not change `dbt_project.yml`. Do not commit — the user commits.
