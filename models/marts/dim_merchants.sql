with merchants as (

    select
        merchant_id
        , business_name
        , industry
        , plan
        , status
        , province
        , signup_date
        , monthly_fee_cents
        , monthly_fee
    from {{ ref('stg_payments__merchants') }}

),

transaction_summary as (

    select
        merchant_id
        , first_transaction_date
        , last_transaction_date
        , lifetime_transaction_count
        , lifetime_gross_volume_cents
        , lifetime_fee_cents
    from {{ ref('int_merchants__transaction_summary') }}

),

final as (

    select
        m.merchant_id
        , m.business_name
        , m.industry
        , m.plan
        , m.status
        , m.status = 'active' as is_active
        , m.province
        , m.signup_date
        , date_diff(m.signup_date, current_date(), day) as tenure_days
        , m.monthly_fee_cents
        , m.monthly_fee
        , ts.first_transaction_date is not null as has_transacted
        , ts.first_transaction_date
        , ts.last_transaction_date
        , coalesce(ts.lifetime_transaction_count, 0) as lifetime_transaction_count
        , coalesce(ts.lifetime_gross_volume_cents, 0) as lifetime_gross_volume_cents
        , coalesce(ts.lifetime_fee_cents, 0) as lifetime_fee_cents

    from merchants as m

    left join transaction_summary as ts
        on m.merchant_id = ts.merchant_id

)

select * from final