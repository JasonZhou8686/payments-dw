---
name: add-tests
description: Propose and add dbt tests for an existing model based on its SQL and sample data — PK, FK, enums, ranges, and one business-rule test. Use when asked to "add tests", "test coverage for <model>", or "/add-tests <model>".
---

# /add-tests <model>

Raise a model to the test standard in `CLAUDE.md` without changing its SQL.

## Steps

1. Read the model SQL and its current YAML entry. List columns and infer each one's role:
   primary key, foreign key, enum/status, money, timestamp/date, boolean, free text.

2. Profile the data for the uncertain ones — run one query, not many:
   ```
   dbt show --inline "select count(*) n, count(distinct <pk>) n_pk, min(<money>) min_amt, ... from {{ ref('<model>') }}" --limit 1
   ```
   and `select distinct <enum_col>` for each enum.

3. Propose the test set **before** writing it. Print a short table: column → test → why. Include:
   - PK: `unique`, `not_null`
   - FKs: `relationships` (`to: ref('<parent>')`, `field: <parent pk>`)
   - Enums: `accepted_values` with the observed set
   - Money/counts: `dbt_expectations.expect_column_values_to_be_between` (min 0 unless negatives are legitimate)
   - Timestamps: `dbt_expectations.expect_column_values_to_be_between` with `max_value: current_timestamp()` style guard
     when future dates would be a bug
   - Exactly one business-rule test. Prefer `dbt_utils.expression_is_true` in YAML; use a singular test in `tests/`
     only when it needs a join.
   Ask the user to confirm or edit the table. If they say "go", proceed.

4. Write the YAML. Preserve existing descriptions; add missing ones (one plain sentence each).

5. `dbt test --select <model>`. If a test fails, do **not** loosen it silently: show the failing rows
   (`dbt show --select <test name>`) and ask whether it is a data bug or a wrong assumption.

6. Report: tests added, pass/fail counts, open questions.
