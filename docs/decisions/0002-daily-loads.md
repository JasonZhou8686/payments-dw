# ADR-0002: The loader loads one day at a time, and is safe to rerun

Status: proposed · Date: 2026-11

## Context
`scripts/generate_data.py` regenerates all 90 days and replaces every raw table on each run. That forces
`dbt build --full-refresh` after every load, so the incremental models never do their real job, and it is not how a
production pipeline loads data. Airflow should run the loader once per day, for that day.

Two problems block that today:
- **The output is not reproducible.** The generator uses Python's global random state and `uuid4()`, so the same day
  comes out with different transactions and IDs on every run. A refund generated today could point at a transaction
  ID that was never loaded.
- **Loads replace whole tables.** There is no way to add or redo one day.

## Decision

### 1. Deterministic generation
- The simulation has a fixed start date, `SIM_START = 2026-07-03`.
- Every random draw for one merchant on one day comes from its own generator, seeded from
  `(merchant_id, day)`. IDs are drawn from that generator too, not from `uuid4()`.
- Faker is seeded as well, so merchant names and signup dates are stable.
- Result: day D's rows are identical whether you generate up to D or up to D + 30.

### 2. A run is "as of" the end of its date
`--date D` means: the data as it would look at the end of day D (`as_of = D + 1 day`). Nothing dated on or after
`as_of` exists yet. That is the rule from the generator fix, applied per run.

### 3. Two kinds of raw table, two load methods

| Table | Kind | Load for `--date D` |
|---|---|---|
| `transactions` | event, never changes | overwrite partition D (`transactions$YYYYMMDD`), partitioned by `created_at` |
| `refunds` | event, never changes | overwrite partition D, partitioned by `created_at` |
| `payouts` | event, never changes | overwrite partition D, partitioned by `payout_date` |
| `chargebacks` | record that changes (status, resolved_at) | replace the whole table with the state as of D |
| `merchants` | record that changes | replace the whole table with the state as of D |

Overwriting a partition with `WRITE_TRUNCATE` on a partition decorator makes each load **idempotent**: running D twice
gives the same table as running it once, with no duplicate rows. Appending would double the data on a retry.

Chargebacks are reloaded in full because a chargeback opened in August can be resolved in September: the row changes
after it was first loaded. A real source would send those changes as updates (CDC). At this size a full snapshot is
simpler and still correct.

### 4. Modes
- `--init` drops and recreates the five raw tables, empty, with the partitioning above. Run once.
- `--date YYYY-MM-DD` loads one day as described. This is what Airflow runs.
- The old full mode is removed.

## Consequences
- After `--init` and a backfill, `dbt build` runs without `--full-refresh`, and the incremental models process only
  recent partitions.
- Each run still simulates every day from `SIM_START` to D, because the chargeback snapshot needs all history. A run
  late in the backfill takes longer than an early one. Acceptable at this size; caching is a later optimisation.
- `fct_transactions`' 14-day lookback now matters for real: a refund loaded on D for a sale on D - 10 changes that
  sale's partition in the fact table.
- CI does not depend on this change: it builds from whatever is in `raw`.
