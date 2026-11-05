-- A refund can never exceed the amount of the transaction it is associated with.
-- Returns failing rows; dbt test passes when zero rows come back.
-- (Will only work once stg_payments__transactions and stg_payments__refunds exist — build those models first.)
select
    r.refund_id
    , r.transaction_id
    , r.amount_cents as refund_amount_cents
    , t.amount_cents as transaction_amount_cents
from {{ ref('stg_payments__refunds') }} as r
inner join {{ ref('stg_payments__transactions') }} as t
    on r.transaction_id = t.transaction_id
where r.amount_cents > t.amount_cents
