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
