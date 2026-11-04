# ADR-0001: Facts are incremental, partition-overwritten, clustered by merchant

Status: accepted · Date: 2026-10

## Context
`transactions` is the largest table and grows daily. BigQuery charges by bytes scanned, so full rebuilds of a
fact table on every run cost more each day and make `dbt build` slower as history grows.

## Decision
- Materialize `fct_*` as `incremental` with `insert_overwrite` on a DATE partition.
- Cluster by `merchant_id` because almost every downstream query filters or groups by merchant.
- Reprocess a trailing window (3 days) to absorb late-arriving refunds/chargebacks instead of doing full refreshes.
- Staging stays as views: zero storage, always reflects the raw load, and the cost lands where it's visible — in the fact build.

## Consequences
- `dbt build --full-refresh` is needed after schema changes to a fact. Document it in the model description.
- Tests on facts run against the whole table, not just the new partitions; keep them cheap (no self-joins on full history).
- Snapshot-based "as-of" dimensions are deferred to v2 (see spec open question).
