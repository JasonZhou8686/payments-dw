with source as (
    select *
    from {{ source('payments', 'refunds') }}
),

renamed as (
    select
        refund_id
        , transaction_id
        , merchant_id
        , created_at
        , date(created_at) as refund_date
        , amount_cents
        , {{ cents_to_dollars('amount_cents') }} as amount
        , reason

    from source

)

select * from renamed