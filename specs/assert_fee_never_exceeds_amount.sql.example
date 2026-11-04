-- Business rule: a processing fee can never be larger than the transaction itself.
-- Returns failing rows; dbt test passes when zero rows come back.
-- (Will only work once stg_payments__transactions exists — build that model first.)
select
    transaction_id
    , amount_cents
    , fee_cents
from {{ ref('stg_payments__transactions') }}
where fee_cents > amount_cents
