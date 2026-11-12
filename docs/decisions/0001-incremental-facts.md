# ADR-0001: Facts are incremental, partition-overwritten, clustered by merchant

Status: accepted · Date: 2026-10 · Updated: 2026-11

## Context
`transactions` is the largest table and grows daily. BigQuery charges by bytes scanned, so full rebuilds of a
fact table on every run cost more each day and make `dbt build` slower as history grows.

## Decision
- Materialize `fct_*` as `incremental` with `insert_overwrite` on a DATE partition.
- Cluster by `merchant_id` because almost every downstream query filters or groups by merchant.
- Reprocess a trailing window on each run instead of doing full refreshes. The window is measured back from the
  latest partition in the table (`_dbt_max_partition`) and is set per model, by how late data can arrive for the
  date it is attributed to:
  - `fct_transactions`: 14 days. Each row carries its refund total, and refunds arrive up to 14 days after the sale.
  - `fct_merchant_daily_revenue`: 3 days. Refunds and chargebacks are counted on the day they were created or
    opened, so old partitions do not change because of them. The window only covers late loads.
- Staging stays as views: zero storage, always reflects the raw load, and the cost lands where it is visible, in
  the fact build.

## Consequences
- `dbt build --full-refresh` is needed after a schema change to a fact (`on_schema_change='fail'` stops the run
  otherwise) and after the raw data is reloaded, because partitions outside the window are not rebuilt.
- CI always runs with `--full-refresh`, so its result does not depend on tables left by earlier runs. The
  incremental path is checked by hand.
- The saving depends on the sources being partitioned on the filter column. `fct_transactions` is. The raw refund
  and chargeback tables are not, so they are scanned in full on every run.
- Measured on this data: `fct_merchant_daily_revenue` scans 4.7 MiB on a full build and 443 KiB incrementally.
  At this size the incremental run is not faster, because the multi-statement script has fixed overhead.
- Tests on facts run against the whole table, not just the new partitions. Keep them cheap.
- Attributes copied from a dimension into an incremental fact (`plan`, `industry` in the daily table) keep the
  value from when the partition was built. As-of values from the snapshot are deferred.
