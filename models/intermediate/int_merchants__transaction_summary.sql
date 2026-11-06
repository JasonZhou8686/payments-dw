with transactions as (
    select
        merchant_id
        , transaction_date
        , amount_cents
        , fee_cents
    from {{ ref('stg_payments__transactions') }}
    where status = 'approved'

),

summary as (
    select
        merchant_id
        , min(transaction_date) as first_transaction_date
        , max(transaction_date) as last_transaction_date
        , count(*) as lifetime_transaction_count
        , sum(amount_cents) as lifetime_gross_volume_cents
        , sum(fee_cents) as lifetime_fee_cents
    from transactions
    group by merchant_id
)

select * from summary