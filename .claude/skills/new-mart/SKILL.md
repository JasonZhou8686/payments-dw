---
name: new-mart
description: Build a complete, tested dbt mart from a spec file in specs/ — checks the spec, inspects inputs, writes the SQL and YAML, builds, reconciles and reports. Use when asked to "build the mart from specs/<file>", "implement this spec", or "/new-mart specs/<file>.md".
---
# /new-mart <spec>

Build a complete, tested mart model from a spec file in `specs/`. The spec defines *what* to build: grain, columns, tests, and business rules. `CLAUDE.md` defines *how* to build it: SQL style, layering, naming, and test standards. Follow both exactly. If the spec is ambiguous, incomplete, or conflicts with `CLAUDE.md`, stop and ask the user for clarification. Do not fill gaps with guesses, and do not edit the spec.

## Inputs
- `spec`: path to a spec file in `specs/` (e.g. `specs/merchant_daily_revenue.md`). If no path is given or the file doesn't exist, list the files in `specs/` and ask which one to use. If there is no suitable spec, stop and ask the user to create one before proceeding.

## Steps

1. **Read and check spec** Read the whole spec file and `CLAUDE.md` before writing anything. 
  - Confirm the spec has these sections: Grain, Inputs, Columns, Config, Tests. If any is missing, stop and ask.
  - Stop and ask, rather than guessing if:
    - the spec has an "open questions" section with anything unresolved that affects this build;
    - a definition can be read more than one way (e.g. a time window without a reference point - "trailing 3 days" from today, or from the last partition);
    - a column's definition, type or test contradicts another part of the spec or `CLAUDE.md`;
    - an input model named in the spec does not exist yet.
  - Items under "Out of scope" or "Future work" are not required for this build. Don't add them.
  - Never edit the spec. If it needs a change, say what and why, and wait.

2. **Inspect the inputs** Before writing any SQL, inspect the real schema of every input model and column named in the spec. Never guess column names or types. 
  - For each input model in the spec, list its columns by running:
    `dbt show --inline "select * from {{ ref('<model>') }}" --limit 1`
  - Check that every column the spec references (keys, date columns, amounts, flags) is present, with the expected meaning: dates are DATE, money is INT64 cents, flags are booleans, etc. If any are missing or different, stop and ask the user to clarify the spec.
  - If a model is missing, or a column is missing, stop and report it, do not rename things to make the SQL fit, and do not change upstream models.
  - Note each input's date column; step 3 uses it for the incremental filter.

3. **Write the SQL** in `models/marts/<model_name>.sql`:
  - Start with a `{{config(...)}}` block taken from the spec's "Config" section.
  - If the spec has a Build approach section, follow it exactly.
  - Structure: `with` once at the top; one CTE per input (aggregate inside it when the grain requires), then a `final` CTE, end with `select * from final`. Commas between CTEs, no comma after the last one.
  - List columns explicitly. Never `select *` from a `ref()`. Use upstream models' public columns (e.g. `card_brand`, not `card.brand`). 
  - Incremental models: in **every** source CTE, add `{% if is_incremental() %} where <that source's date column> >= date_sub(_dbt_max_partition, interval <N> day) {% endif %}` with N from the spec's Config section.
  - After left joins: `coalesce(..., 0)` for counts and money, leave dates and attributes null.
  - Output columns in the same order and with the same names as the spec's Columns table.
  - Before running anything, re-read the SQL and check: no duplicate output column names, no unused columns in source CTEs, every spec column present.

4. **Write the YAML** as a new entry in `models/marts/_marts__models.yml`
  - Append the new model, do not modify or reorder existing entries in the file.
  - Model description: purpose, grain, and the "why" from the spec - Window rationale, caveats, anything an analyst could misread (e.g. "chargebacks deducted when opened, not final"). 
  - Describe every column, in the same order as the SQL. Descriptions must match the spec and the data.
  - Add exactly the tests the spec lists - no more, no fewer. Test parameters go under `arguments:`, model-level tests go under the model, beside `columns:` not under a column.
  - Use only test names that exist in dbt core, `dbt_utils` or `dbt_expectations`. If unsure, check the package in `dbt_packages/` rather than guessing.
  - Run `dbt parse` and fix any errors before building.

5. **Build and verify**
  - `dbt run --select <model_name>`. If it fails on a schema change because an earlier version of the table exists, rerun with `--full-refresh` for this model only.
  - `dbt show --select <model_name> --limit 10`. Sanity-check the values against the spec definitions.
  - `dbt build --select <model_name>` to rebuild and run all tests.
  - Incremental models: run `dbt run --select <model_name>` a second time and confirm it reports `SCRIPT` (incremental), not `CREATE TABLE`. Note bytes processed for both runs.
  - Run each reconciliation check from the spec as a read-only query with `dbt show --inline`, and record the expected and actual numbers.
  - If any test fails or a reconciliation doesn't match: show the failing rows (`dbt show --select <test_name>`) and stop. Do not change tests, thresholds, the spec or the SQL to make it pass

6. **Report** in this format, nothing else:
  - Files: created/changed
  - Rows: total, and date range of `activity_date` (or the partition column)
  - Tests: passed/failed count; failures with failing rows
  - Incremental: bytes processed on first vs second run
  - Reconciliation: each check, expected vs actual, match yes/no
  - Decisions: anything the spec didn't specify that you had to decide, and why
  - Questions: anything that needs the user's input

## Do not
- Edit the spec, `CLAUDE.md`, `dbt_project.yml`, or any model other than the one being built.
- Remove, rename or reorder existing entries in YAML files.
- Loosen, delete or skip a failing test.
- Build anything listed under "Out of scope".
- Commit, push, or run `--full-refresh` on any model other than the one being built.
