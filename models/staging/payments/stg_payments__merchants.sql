with source as (

    select * from {{ source('payments', 'merchants') }}

),

renamed as (

    select
        merchant_id
        , business_name
        , industry
        , plan
        , status
        , province
        , signup_date
        , monthly_fee_cents
        , {{ cents_to_dollars('monthly_fee_cents') }} as monthly_fee
        , updated_at

    from source

)

select * from renamed
