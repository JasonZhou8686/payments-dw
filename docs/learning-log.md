# Learning log

## Day 1 — 2026-11-04: setup, first models, first agent run

### BigQuery / GCP
- Project = billing + permission boundary; datasets hold tables. Tools use the Project ID (`payments-dw`), not the display name.
- Service account `dbt-runner` = machine identity. Gave it **BigQuery Data Editor + Job User** (least privilege) instead of Admin; Data Editor includes dataset creation so everything worked.
- Key file lives outside the repo at `~/.gcp/dbt-runner.json`, `chmod 600`; `.gitignore` blocks `*.json` as a second layer.
- Every BigQuery call today (dbt debug/build/show, the Python loader, Claude Code's queries) ran as `dbt-runner` — via `profiles.yml` for dbt and `GOOGLE_APPLICATION_CREDENTIALS` for Python. Visible in BigQuery → Job history.
- Nested data: `card` is a STRUCT (dot-notation), `line_items` is ARRAY<STRUCT> (`UNNEST` changes grain — not in staging).
- Load jobs are free; views cost nothing until queried; cost = bytes scanned.
- TODO tomorrow: replace key file with `impersonate_service_account` (user ADC → impersonate dbt-runner; needs gcloud SDK, iamcredentials API, Token Creator role). CI would use Workload Identity Federation.

### dbt
- Model = one `.sql` = one view/table named after the file. dbt wraps the `select` in DDL.
- `{{ source() }}` / `{{ ref() }}` replace hard-coded names and build the dependency graph.
- Macros (`cents_to_dollars`) = reusable Jinja SQL.
- `dbt_project.yml` sets folder-level defaults (materialization, schema). `profiles.yml` (outside repo) holds connections; `profile:` links them.
- Tests are declared in YAML → compile to "query for bad rows; zero rows = pass". Built-ins: unique, not_null, accepted_values, relationships. Packages add more. Singular tests = your own `.sql` in `tests/`.
- Snapshots = SCD2: first run CREATE, later runs MERGE only changes (`dbt_valid_from/to`).
- Commands: `dbt deps` (packages), `dbt debug`, `dbt build` (run+test+snapshot in order), `dbt show`, `dbt compile`.
- Layers: staging (1:1 raw, views, rename/cast only) → intermediate (joins/logic) → marts (fct_/dim_, tables).
- New YAML style (dbt ≥1.10): `loaded_at_field`/`freshness` under `config:`; test params under `arguments:`.

### Shell / tooling
- `~` = home; dot-folders hidden. `~/.zshrc` runs on every new Terminal.
- `source file` runs a file in the *current* shell — needed for `.venv/bin/activate` and `.zshrc`.
- `python3 -m venv .venv` isolates packages; `(.venv)` in prompt = active.
- `PATH` = where commands are found; "command not found" after install ≈ PATH.
- python.org Mac Python lacks SSL certs → `/Applications/Python 3.12/Install Certificates.command`.

### Git
- `git add` stages, `git commit` snapshots; `git status` in between. `-A` = all changes incl. deletions, respecting `.gitignore`.
- `git rm --cached` untracks without deleting. `--amend --reset-author` rewrites last commit. `git log --oneline` = history.

### Working with Claude Code
- `CLAUDE.md` = standing project rules; it read them correctly and caught a stale fact (Python 3.11→3.12).
- Skill = markdown procedure in `.claude/skills/<name>/SKILL.md`, invoked as `/<name>`; can also auto-trigger from its description.
- Permission modes: switched from auto to default so every edit/command is reviewed (Shift+Tab).
- `/new-source transactions`: it stopped and asked for the schema (didn't guess), wrote one profiling query for all enums + negative-money checks, built the model + 14 tests, and reported 3 open decisions instead of deciding silently.
- My role = reviewer: verify edits myself (`grep`), read each command before approving, judge against CLAUDE.md.

### Decisions made (interview stories)
- Least-privilege roles over Admin.
- `accepted_values: [CAD]` kept strict — let the test fail when the business changes.
- `card.last4` left inside the struct (PCI-adjacent → harder to reach).
- `metadata_json` left unparsed in staging — parsing is business logic.

### State at end of day
- Models: `stg_payments__merchants` (7 tests), `stg_payments__transactions` (14 tests); `merchants_snapshot`. `dbt build` → PASS.
- Commits: scaffold; (pending) transactions model.
- Next: `refunds` by hand → move `assert_fee_never_exceeds_amount` into `tests/` → `/new-source chargebacks`, `/new-source payouts` → impersonation setup.

## Day 2 — 2026-11-05: staging layer complete, first PR with CI

### What I built
- `stg_payments__refunds` by hand (SQL + YAML), then `stg_payments__chargebacks` and `stg_payments__payouts` with `/new-source`.
- Singular tests in `tests/`: `assert_fee_never_exceeds_amount`, `assert_refund_not_above_transaction`.
- Model-level tests: payouts `net_cents = gross_cents - fees_cents - refunds_cents`; chargebacks
  `(status = 'pending') = (resolved_at is null)`.
- Pushed to GitHub, added CI secrets, merged PR #1 (generator fix) through CI.

### dbt
- Naming: `stg_<source>__<table>` — the double underscore separates source system from table.
- `dbt show` adds its own `limit`; use `--limit N`, not `limit` in the SQL.
- `dbt parse` validates YAML/Jinja without touching BigQuery; run it after YAML edits.
- Generic tests = YAML; singular tests = `.sql` in `tests/` returning bad rows. `dbt test --select test_type:singular`.
- Selectors: `model+` (downstream), `+model` (upstream), `path:models/staging`, `test_type:`, `source:`.
- Implication "A → B" in SQL = `not A or B`; two-way = `(A) = (B)`. Nulls make the whole expression null and
  slip through `expression_is_true` → add `not_null` on the inputs.

### YAML
- Indentation is the syntax. models → columns → tests. Tests with parameters nest under `arguments:`.
- Quote values that YAML would reinterpret (`yes`/`no`/`NO`, `null`, leading zeros). Plain words don't need quotes.
- Profile the data before writing tests — and then actually use the result (I first called `reason` "free-form").

### Mistakes and lessons
- Copied `fee_cents`/`currency`/`status` into refunds from the transactions template without checking the schema —
  exactly what the skill's "never guess the schema" step prevents.
- Skill edit #1: `INFORMATION_SCHEMA.COLUMNS` fallback when `bq` is missing. My first draft queried the data table
  instead — tested the query before committing.
- Skill edit #2: my nullable rule was too literal ("schema nullable → no not_null") and the agent applied it
  faithfully, dropping valid tests. **A skill edit is a code change: test the rule, not just the query.**
- The agent found a real generator bug (pending chargebacks with `resolved_at`) and stopped to ask instead of
  papering over it.

### Git / GitHub
- One logical change per commit; `git diff --cached` on anything unexpected; `git restore --staged` to split.
- PR = request to merge a branch, with diff review and checks. CI (GitHub Actions) rebuilds and tests everything on
  a clean runner against `dbt_ci`. First run failed (blank project → missing secret), fixed, re-ran, merged.

## Day 3 — 2026-11-06: first marts

### What I built
- `int_merchants__transaction_summary`: approved-only lifetime activity per merchant (reusable aggregation).
- `dim_merchants`: all 500 merchants, current attributes + `is_active`, `tenure_days`, `has_transacted`, lifetime
  counts/volume/fees.
- `fct_transactions`: incremental `insert_overwrite`, partitioned by `transaction_date`, clustered by `merchant_id`,
  14-day lookback; all statuses kept with `is_approved`; refund totals joined.
- PRs #2, #3, #4 merged through CI.

### Concepts
- Mart = finished tables built for users (Gold layer). Fact = events/numbers to sum; dimension = things/attributes
  to group by. Star schema.
- CTEs: `with` once, commas between, no comma after the last; a CTE only exposes the columns it selects.
- Left join keeps every left row; unmatched right columns are null. `coalesce(…, 0)` for counts/money (nothing = zero),
  leave dates null (nothing = never happened).
- Config hierarchy: dbt default → `dbt_project.yml` by folder → model YAML `config:` → `{{ config() }}` in the SQL.
- `dbt run` builds only; `dbt build` builds and tests (and stops downstream on failure); `dbt test` only tests.
- dbt never deletes renamed/removed models — orphans stay in BigQuery until cleaned up.
- Reconcile marts against the layer below (136,653 approved in mart ≈ 95.5% of staging).

### Incremental models
- `is_incremental()` is false on the first run, true afterwards; `_dbt_max_partition` = latest partition in the table.
- `insert_overwrite` replaces whole date partitions inside the window (BigQuery `SCRIPT`), idempotent.
- Lookback window ≥ the late-arrival SLA of the slowest upstream event attributed to that date (refunds: 14 days;
  chargebacks: ~60, out of scope here).
- Measured: full build `CREATE TABLE` 143.1k rows / 14.0 MiB; incremental rerun `SCRIPT` 6.0 MiB but slower —
  fixed overhead dominates at small scale. You pay for bytes, not seconds.
- When NOT incremental: small tables, unbounded history changes, whole-history logic, dimensions, early schema churn,
  exact-reconciliation reporting.

### Mistakes and lessons
- Twice a fix was only half-saved; the next build/test caught it. Save, re-read the file, then build.
- Test name typo (`expect_table_row_count_to_be_equal_to`) = compilation error (code problem), not a FAIL (data problem).
- Committed on `main` by accident → `git checkout -b <branch>` then `git branch -f main origin/main`.
- Merged PR #3 before pushing the last commit → the CI change was stranded on the branch; recovered with a new PR.
  **Merge after the last push — check the PR's Commits tab first.**

### GitHub
- Branch protection is not enforced on private repos on the free plan; rule saved for when the repo goes public.
- Removed the CI `paths:` filter so `build` can be a required check without blocking docs-only PRs; Python 3.12.
- Enabled cleanup of merged branches; `git fetch --prune` to drop stale remote refs.

### State at end of day
- Staging 5 models, intermediate 1, marts 2 (`dim_merchants`, `fct_transactions`), ~108 tests, 4 PRs merged.
- Next: fix the `merchant_daily_revenue` spec, write a `/new-mart` skill, build the mart with it.

## Day 4 — 2026-11-07 to 2026-11-10: a spec, my first skill, and a mart built by the agent

### What I built
- Rewrote `specs/fct_merchant_daily_revenue.md` to v1, then wrote `.claude/skills/new-mart/SKILL.md`.
- Ran `/new-mart` on the spec. It built `fct_merchant_daily_revenue`: one row per merchant per day, incremental,
  3-day lookback, 27 tests. PR #5.

### Specs
- The first draft had real flaws: dollars where the fact stores cents, a `>= 0` test on a net column that can be
  negative, "trailing 3 days" with no reference point, and a build that started from transactions and would have
  dropped days with only a refund or chargeback.
- The spine: aggregate each event source to (merchant, day), `union distinct` the keys, left join the aggregates.
- The lookback window depends on which date an event is attributed to. A refund counted on the day it was created
  never changes an old partition, so 3 days is enough here, while `fct_transactions` needs 14.
- A column definition says what the column is. A reconciliation is a check. Keep them in separate sections.
- Write down what is out of scope, or the agent will helpfully build it.
- Still wrong after two reviews: `plan` and `industry` were called "current values", but an incremental table keeps
  whatever value was there when the partition was built.

### Writing a skill
- Frontmatter `description` decides when the skill is used. Mine was still the copied `new-source` text at first.
- Turn every question into an instruction with a concrete check. "What should make it stop?" is not an instruction.
- The spec says what to build, `CLAUDE.md` says how. If they conflict, stop and ask. Never edit the spec.
- "Append, don't modify existing entries" for shared YAML files. A wrong filename (`_marts_models.yml`) would have
  made the agent write a second file.
- Fixed report format, so every run is reviewed the same way.
- Commit the skill before running it.

### What the first run taught me
- It stopped on a real conflict I had missed: the model name had no `fct_` prefix.
- "Exactly the tests the spec lists" contradicted the tests `CLAUDE.md` requires. Rule is now: spec tests plus
  `CLAUDE.md` tests, ask if they contradict.
- It used `INFORMATION_SCHEMA` for column types instead of my `select * limit 1`. Better, so the skill says that now.
- `dbt show --select` fails on an incremental model that uses `_dbt_max_partition`. Preview with `--inline` instead.
- It reported done without making a correction I had asked for. Ask directly and read the diff.
- Reconciled exactly: 136,653 approved transactions, 25,908,511 refund cents, 798 chargebacks.
- It found 31 chargebacks dated in the future, which had moved the incremental window to late November.

### Git
- `git mv` stages the rename. `git restore --staged .` clears staging without losing work, so commits stay one
  logical change each.
- A push does not open a pull request. Merging does not delete the branch unless the repo setting is on.

## Day 5 — 2026-11-11: honest data, and a CI failure

### What I built
- Generator fix: the data is a snapshot as of its end date. Refunds and chargebacks that would happen after it are
  not generated, and a chargeback whose resolution would fall after it stays pending. PR #7, closes issue #6.
- Three staging tests that fail on any future-dated row.
- CI now runs `dbt build --full-refresh`.

### Lessons
- Dropping events that have not happened yet is more honest than capping their dates, which would pile them on the
  last day.
- Estimate the effect before looking: refunds lag 7 days on average, 7/90 is about 8%, and refunds fell 7%.
  Chargebacks lag about 32 days, 32/90 is about 36%, and they fell 34%.
- Before and after, max date: refunds 2026-10-14 → 2026-09-30, chargebacks 2026-11-27 → 2026-09-30.
- After reloading raw data, every environment needs a full refresh, including CI. CI failed on the row-count test
  for `fct_transactions` because its tables were left from earlier runs and mixed old and new data.
- Reading a failed CI log: one real failure. The 28 skips and the cancels were `--fail-fast`.
- Honest incremental number for `fct_merchant_daily_revenue`: 443 KiB against a full build of 4.7 MiB. The
  earlier 1.1 KiB was the window sitting on nearly empty days.
- An incremental filter only saves bytes on sources partitioned on the filter column.

### State at end of day
- Staging 5, intermediate 1, marts 3, 1 snapshot, 138 tests, 6 PRs merged, CI green.
- Next: README, make the repo public, then orchestration.

## Day 6 — 2026-11-12 to 2026-11-16: Airflow, daily loads and a backfill

### What I built
- Airflow 3.4 running locally with `airflow standalone`, and a DAG `payments_pipeline` with two tasks:
  `load_raw >> dbt_build`. First version ran by hand only. PR #9.
- A loader that loads one day per run (`--init` once, then `--date D`), deterministic and safe to rerun.
  ADR-0002.
- A daily schedule, a backfill from July 4 to November 14, and the first run the scheduler started by itself on
  November 16. PR #11.

### Airflow
- Two virtual environments: `.venv` for dbt and the loader, `.venv-airflow` only for `airflow` commands.
  Airflow's dependencies clash with dbt's, so it's installed with the constraints file.
- Config by environment variable is `AIRFLOW__SECTION__KEY`, with double underscores. I typed single underscores
  and Airflow quietly used its default folder.
- `{{ ds }}` is the run's logical date. `airflow tasks render` shows the command with the date filled in, without
  running anything.
- In Airflow 3, `schedule="@daily"` runs *for* the day it starts. `CronDataIntervalTimetable("@daily")` gives each
  run a whole day that has already ended, like Airflow 2 did. This has to be chosen on purpose.
- Run IDs are named after when the run may start, not the day it loads: `backfill__2026-07-05` loads July 4. The
  UI shows times in local time, so midnight UTC on Nov 16 shows as Nov 15 18:00.
- `airflow backfill create` only creates the runs. The scheduler runs them, and it won't run anything for a paused
  DAG. I set `end_date` so unpausing didn't also schedule today.
- `max_active_runs=1` keeps the days in order, which the incremental lookback windows depend on.
- `catchup=False` runs only the latest missed day. Older gaps need a backfill.
- Airflow keeps one scheduled run per logical date. A bad run holds its date until you clear it.

### Idempotent and deterministic loads
- Idempotent: each day is loaded with `WRITE_TRUNCATE` into a partition decorator (`transactions$20260703`).
  Loading July 3 twice gave 748 rows and 748 distinct IDs both times.
- Deterministic: one random generator per merchant and day, seeded from a hash of the two. No global `random`,
  no `uuid4`, Faker seeded. Every value is drawn first and filtered by the as-of time after, so a later run draws
  the same numbers for the same day.
- Events that never change (transactions, refunds, payouts) go into day partitions. Chargebacks and merchants
  change after they're first loaded, so each run replaces them whole. Event vs record decides the load method.
- Before loading anything to BigQuery, checked 29 local daily runs: every reference resolves, the chargeback
  snapshot only grows, and no ID appears on two days.

### Mistakes and lessons
- The first scheduled run loaded a day that hadn't ended: old `@daily` semantics, and a DAG I thought was
  paused. The relationships tests caught it, 727 chargebacks pointing at transactions that were never loaded.
  Fixes: the interval timetable, and the loader now refuses any date that hasn't ended in UTC.
- I copied the error message along with the check above it. The check worked and the message was wrong. An error
  message has to describe the check that raised it.
- A VS Code tab still showed the old loader after the agent rewrote the file. Saving it would have put the old
  version back. The file on disk is what runs, and `git diff` shows what's on disk.
- A task died with exit code -15 (SIGTERM) because the Mac went to sleep. Rerunning it was safe because the load
  is idempotent. Added 2 retries, and ran the long backfill under `caffeinate -i` with the lid open.
- `load_raw` had finished before the kill, and July 4 was complete in raw. BigQuery load jobs are atomic, so a
  partition is either all there or not there.
- After pushing the branch I switched to `main`, which still had the old DAG with no schedule, and Airflow
  started running that. Airflow runs whatever is checked out in `dags/`. Run it from `main`, after a merge.
- The bad run from the first morning held the Nov 15 slot, so the scheduler never made another one. I only found
  the gap by comparing `max(date)` in raw and in `fct_transactions`. Cleared the run and it loaded Nov 15.

### Numbers
- July 3 to September 30: 90 days, 104,765 transactions in both raw and `fct_transactions`, and 99,995 approved
  in both the fact and the daily table. Fewer than the old 142,600 because merchants now only trade after they
  sign up.
- The weekend shows up: Friday July 3 had 748 transactions, Saturday and Sunday about 1,000, Monday 814.
- A daily run takes under 2 minutes: about 20 seconds to load, 90 seconds for `dbt build`.

### State at end of day
- July 3 to November 16 loaded, one run per day. `dbt test` 138/138.
- The DAG runs every day at midnight UTC (18:00 Calgary) while `airflow standalone` is running.
- Next: freshness checks and what happens when a test fails, then containers.
