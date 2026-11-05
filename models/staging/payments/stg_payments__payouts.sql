with source as (

    select * from {{ source('payments', 'payouts') }}

),

renamed as (

    select
        payout_id
        , merchant_id
        , payout_date
        , gross_cents
        , {{ cents_to_dollars('gross_cents') }} as gross
        , fees_cents
        , {{ cents_to_dollars('fees_cents') }} as fees
        , refunds_cents
        , {{ cents_to_dollars('refunds_cents') }} as refunds
        , net_cents
        , {{ cents_to_dollars('net_cents') }} as net
        , status
        , created_at

    from source

)

select * from renamed
