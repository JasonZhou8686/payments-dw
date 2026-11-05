with source as (

    select * from {{ source('payments', 'chargebacks') }}

),

renamed as (

    select
        chargeback_id
        , transaction_id
        , merchant_id
        , amount_cents
        , {{ cents_to_dollars('amount_cents') }} as amount
        , reason_code
        , status
        , opened_at
        , date(opened_at) as chargeback_date
        , resolved_at

    from source

)

select * from renamed
