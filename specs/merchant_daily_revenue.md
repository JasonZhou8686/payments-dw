# Spec: `merchant_daily_revenue`

Status: draft · Owner: Jason · Layer: marts

## Purpose
One row per merchant per day summarising money movement, for the merchant-health dashboard and as a feature table
for a churn model. Must be cheap to query for the last 30 days.

## Grain
`(merchant_id, activity_date)`. A row exists only for days with at least one approved transaction, refund, or chargeback.

## Inputs
- `fct_transactions` (approved only)
- `stg_payments__refunds`
- `stg_payments__chargebacks` (count by `opened_at`, amount by `opened_at`)
- `dim_merchants` for `plan` and `industry` (current values, not as-of)

## Columns
| column | type | definition |
|---|---|---|
| merchant_daily_id | STRING | surrogate key: `{{ dbt_utils.generate_surrogate_key(['merchant_id','activity_date']) }}` |
| merchant_id | STRING | FK → dim_merchants |
| activity_date | DATE | partition column |
| plan, industry | STRING | from dim_merchants |
| transaction_count | INT64 | approved transactions that day |
| gross_volume | NUMERIC | sum of approved amount (dollars) |
| fee_revenue | NUMERIC | sum of fees (dollars) — this is *our* revenue |
| refund_amount | NUMERIC | sum of refunds created that day |
| chargeback_count | INT64 | chargebacks opened that day |
| chargeback_amount | NUMERIC | sum of chargeback amounts opened that day |
| net_volume | NUMERIC | gross_volume − refund_amount − chargeback_amount |
| avg_ticket | NUMERIC | gross_volume / transaction_count, null if count = 0 |

## Config
Incremental, `insert_overwrite`, partition by `activity_date`, cluster by `merchant_id`. Reprocess the trailing 3 days on
each run (refunds/chargebacks arrive late).

## Tests
- PK unique/not_null; FK to dim_merchants
- `net_volume <= gross_volume`
- `fee_revenue <= gross_volume`
- `transaction_count >= 0`, all money columns `>= 0`
- Row count per day roughly stable: warn if any day has < 50% of the 7-day median (dbt_expectations)

## Open questions
- Should `plan` be as-of the activity date (needs the snapshot) rather than current? Decide before v2.
