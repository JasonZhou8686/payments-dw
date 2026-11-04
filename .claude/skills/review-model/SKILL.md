---
name: review-model
description: Review one or more dbt models (or a git diff) against this project's CLAUDE.md conventions and output a prioritized review. Use when asked to "review", "check this model", "code review", or "/review-model <model|--diff>".
---

# /review-model <model name | --diff>

Act as the senior reviewer on this project. Judge only against `CLAUDE.md` and standard dbt practice; do not restyle for taste.

## Steps

1. Scope: if given `--diff`, run `git diff --name-only HEAD` (or the staged set) and review changed `.sql`/`.yml` under `models/`,
   `snapshots/`, `tests/`, `macros/`. Otherwise review the named model, its YAML entry, and any singular tests that reference it.

2. Check, in this order, and collect findings:
   - **Layering**: correct folder/prefix; staging uses only `source()`; marts never `select *`; no `raw.*` references outside staging.
   - **Config**: facts are incremental + `insert_overwrite` + partitioned by a date + clustered by `merchant_id`, with an `is_incremental()` filter.
   - **Naming**: snake case; `_at` / `_date` / `is_` / `_cents` conventions; PK first and named `<entity>_id`.
   - **Tests/docs**: YAML entry exists; model + every column described; PK unique/not_null; FKs `relationships`; enums `accepted_values`;
     money ranges; ≥1 business-rule test for facts.
   - **SQL quality**: CTE structure, leading commas, `safe_cast`, `qualify` for dedup, no correlated subqueries, no `select distinct` to hide a fan-out.
   - **Cost**: any full-table scan of `transactions` without a partition filter; `select *` on wide tables; unnecessary `order by`.
   - **Safety**: no credentials, project IDs or dataset names hard-coded.

3. Run `dbt compile --select <model>` and skim the compiled SQL in `target/compiled/` for anything the Jinja hid.

4. Output format:
   ```
   ## Review: <model>
   ### Must fix (blocks merge)
   - file:line — issue — why — suggested change
   ### Should fix
   - ...
   ### Nice to have
   - ...
   ### Looks good
   - one or two things done well (specific)
   Verdict: APPROVE | REQUEST CHANGES
   ```
   Keep every bullet to one line. Do not edit files unless the user asks you to apply the fixes.
