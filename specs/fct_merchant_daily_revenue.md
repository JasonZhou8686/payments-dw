# Spec: `fct_merchant_daily_revenue`

Status: ready · Owner: Jason · Layer: marts · Version: v1

## Purpose
One row per merchant per day summarising money movement, for the merchant-health dashboard and as a feature table
for a churn model. Must be cheap to query for the last 30 days (partition pruning on `activity_date`).

## Grain
`(merchant_id, activity_date)`. A row exists only for days with at least one approved transaction, refund, or
chargeback. A merchant can have refunds or chargebacks on a day with no sales, so those days must still appear.

## Inputs
- `fct_transactions` — approved only (`is_approved`), dated by `transaction_date`
- `stg_payments__refunds` — dated by `refund_date` (the day the refund was created)
- `stg_payments__chargebacks` — dated by `chargeback_date` (the day it was opened)
- `dim_merchants` — `plan` and `industry`, value at the time the partition is built; not updated later

## Build approach
1. Aggregate each event source to `(merchant_id, activity_date)` separately: transactions, refunds, chargebacks.
2. Build the key spine: `union distinct` of the three `(merchant_id, activity_date)` sets.
3. Left join the three aggregates and `dim_merchants` onto the spine.
4. `coalesce(…, 0)` all counts and money from the aggregates; derive `net_volume_cents` and `avg_ticket_cents`.

Do not start from transactions and left join refunds/chargebacks — that drops days with refunds or chargebacks but no
sales.

## Columns
| column | type | definition |
|---|---|---|
| merchant_daily_id | STRING | surrogate key: `{{ dbt_utils.generate_surrogate_key(['merchant_id','activity_date']) }}` |
| merchant_id | STRING | FK → dim_merchants |
| activity_date | DATE | partition column; UTC calendar day |
| plan | STRING | from dim_merchants, as of when the partition was last built |
| industry | STRING | from dim_merchants, as of when the partition was last built |
| transaction_count | INT64 | approved transactions that day; 0 if none |
| gross_volume_cents | INT64 | sum of approved `amount_cents`; 0 if none |
| fee_revenue_cents | INT64 | sum of `fee_cents` on approved transactions — this is *our* revenue; 0 if none |
| refund_count | INT64 | refunds created that day; 0 if none |
| refund_amount_cents | INT64 | sum of refunds created that day; 0 if none |
| chargeback_count | INT64 | chargebacks opened that day; 0 if none |
| chargeback_amount_cents | INT64 | sum of chargeback amounts opened that day; 0 if none |
| net_volume_cents | INT64 | gross_volume_cents − refund_amount_cents − chargeback_amount_cents; **can be negative**; Chargebacks are deducted when opened, regardless of outcome; this is exposure, not final settlement |
| avg_ticket_cents | NUMERIC | round(cast(safe_divide(gross_volume_cents, transaction_count) as numeric), 2); null when transaction_count = 0 |

Money is stored in cents (INT64) to match `fct_transactions`; dollars belong in the BI layer.

## Config
Incremental, `insert_overwrite`, partition by `activity_date`, cluster by `merchant_id`, `on_schema_change='fail'`.
Filter each source on `<its date column> >= date_sub(_dbt_max_partition, interval 3 day)`.

Why 3 days and not 14 like `fct_transactions`: here refunds and chargebacks are attributed to the day they were
*created/opened*, not to the original transaction's day. A refund created today lands in today's partition, so old
partitions never need rewriting because of refund lag. The window only has to cover load delay (yesterday's data
arriving late). Apply the same window to all three source CTEs, each filtered on its own date column.

## Tests
- `merchant_daily_id` unique + not_null
- `merchant_id` not_null + relationships → `dim_merchants`
- `activity_date` not_null
- Combination of `merchant_id` + `activity_date` unique (`dbt_utils.unique_combination_of_columns`)
- All counts and money columns not_null (guards the coalesce)
- Counts, `gross_volume_cents`, `fee_revenue_cents`, `refund_amount_cents`, `chargeback_amount_cents` `>= 0`
- **No** `>= 0` test on `net_volume_cents` (negative days are legitimate)
- Model-level `expression_is_true`:
  - `fee_revenue_cents <= gross_volume_cents`
  - `net_volume_cents = gross_volume_cents - refund_amount_cents - chargeback_amount_cents`
  - `transaction_count + refund_count + chargeback_count > 0` (every row has at least one event — guards the grain)
- `avg_ticket_cents` `>= 0` (nulls allowed)
- `accepted_values` on `plan` and `industry`, same values as `dim_merchants` (CLAUDE.md standard)
- Reconciliation (check once, manually): `sum(transaction_count)` equals approved rows in `fct_transactions`;
  `sum(refund_amount_cents)` equals total refunds in staging; `sum(chargeback_count)` equals rows in
  `stg_payments__chargebacks`.

## Operations
After reloading raw data (e.g. re-running the generator), run `dbt build --full-refresh --select fct_transactions+` - incremental models keep old partitions outside the lookback window, so they will not match the new raw data otherwise.

## Out of scope for v1
- Day-over-day row-count stability check (< 50% of 7-day median) — not a built-in test; future singular test.
- As-of `plan`/`industry` using `merchants_snapshot`, or dropping them from this table and joining `dim_merchants` at query time. v1 keeps the value from when the partition was built.
- merchant-local days
- Enforcing partition filters (`require_partition_filter=true`) - would make dbt's own full-table tests fail.


