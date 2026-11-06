{{
    config(
        materialized='incremental',
        incremental_strategy='insert_overwrite',
        partition_by={
            "field": "transaction_date",
            "data_type": "date"},
        cluster_by=['merchant_id'],
        on_schema_change='fail'
    )
}}

with transactions as (

    select
        transaction_id
        , merchant_id
        , transaction_date
        , created_at
        , channel
        , currency
        , card_brand
        , card_funding
        , card_country
        , amount_cents
        , fee_cents
        , status
    from {{ ref('stg_payments__transactions') }}
    {% if is_incremental() %}
    where transaction_date >= date_sub(_dbt_max_partition, interval 14 day)
    {% endif %}

),

refunds as (

    select
        transaction_id
        , sum(amount_cents) as refunded_amount_cents
    from {{ ref('stg_payments__refunds') }}
    group by transaction_id

),

final as (
    
    select
        t.transaction_id
        , t.merchant_id
        , t.transaction_date
        , t.created_at
        , t.status
        , t.status = 'approved' as is_approved
        , t.channel
        , t.currency
        , t.card_brand
        , t.card_funding
        , t.card_country
        , t.amount_cents
        , t.fee_cents
        , coalesce(r.refunded_amount_cents, 0) as refunded_amount_cents
        , coalesce(r.refunded_amount_cents, 0) > 0 as is_refunded
        , t.amount_cents - coalesce(r.refunded_amount_cents, 0) as net_amount_cents
    from transactions as t
    left join refunds as r
        on t.transaction_id = r.transaction_id

)

select * from final