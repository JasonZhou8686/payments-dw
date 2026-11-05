with source as (

    select * from {{ source('payments', 'transactions') }}

),

renamed as (

    select
        transaction_id
        , merchant_id
        , created_at
        , date(created_at) as transaction_date
        , amount_cents
        , {{ cents_to_dollars('amount_cents') }} as amount
        , fee_cents
        , {{ cents_to_dollars('fee_cents') }} as fee
        , currency
        , status
        , channel
        , card
        , card.brand as card_brand
        , card.funding as card_funding
        , card.country as card_country
        , line_items
        , metadata_json

    from source

)

select * from renamed
