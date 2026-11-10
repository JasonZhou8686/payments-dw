{{
    config(
        materialized='incremental',
        incremental_strategy='insert_overwrite',
        partition_by={
            "field": "activity_date",
            "data_type": "date"},
        cluster_by=['merchant_id'],
        on_schema_change='fail'
    )
}}

with transactions as (

    select
        merchant_id
        , transaction_date as activity_date
        , count(*) as transaction_count
        , sum(amount_cents) as gross_volume_cents
        , sum(fee_cents) as fee_revenue_cents
    from {{ ref('fct_transactions') }}
    where is_approved
    {% if is_incremental() %}
        and transaction_date >= date_sub(_dbt_max_partition, interval 3 day)
    {% endif %}
    group by merchant_id, transaction_date

),

refunds as (

    select
        merchant_id
        , refund_date as activity_date
        , count(*) as refund_count
        , sum(amount_cents) as refund_amount_cents
    from {{ ref('stg_payments__refunds') }}
    {% if is_incremental() %}
    where refund_date >= date_sub(_dbt_max_partition, interval 3 day)
    {% endif %}
    group by merchant_id, refund_date

),

chargebacks as (

    select
        merchant_id
        , chargeback_date as activity_date
        , count(*) as chargeback_count
        , sum(amount_cents) as chargeback_amount_cents
    from {{ ref('stg_payments__chargebacks') }}
    {% if is_incremental() %}
    where chargeback_date >= date_sub(_dbt_max_partition, interval 3 day)
    {% endif %}
    group by merchant_id, chargeback_date

),

merchants as (

    select
        merchant_id
        , plan
        , industry
    from {{ ref('dim_merchants') }}

),

spine as (

    select merchant_id, activity_date from transactions
    union distinct
    select merchant_id, activity_date from refunds
    union distinct
    select merchant_id, activity_date from chargebacks

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['s.merchant_id', 's.activity_date']) }} as merchant_daily_id
        , s.merchant_id
        , s.activity_date
        , m.plan
        , m.industry
        , coalesce(t.transaction_count, 0) as transaction_count
        , coalesce(t.gross_volume_cents, 0) as gross_volume_cents
        , coalesce(t.fee_revenue_cents, 0) as fee_revenue_cents
        , coalesce(r.refund_count, 0) as refund_count
        , coalesce(r.refund_amount_cents, 0) as refund_amount_cents
        , coalesce(c.chargeback_count, 0) as chargeback_count
        , coalesce(c.chargeback_amount_cents, 0) as chargeback_amount_cents
        , coalesce(t.gross_volume_cents, 0)
            - coalesce(r.refund_amount_cents, 0)
            - coalesce(c.chargeback_amount_cents, 0) as net_volume_cents
        , round(cast(safe_divide(t.gross_volume_cents, t.transaction_count) as numeric), 2) as avg_ticket_cents
    from spine as s
    left join transactions as t
        on s.merchant_id = t.merchant_id
        and s.activity_date = t.activity_date
    left join refunds as r
        on s.merchant_id = r.merchant_id
        and s.activity_date = r.activity_date
    left join chargebacks as c
        on s.merchant_id = c.merchant_id
        and s.activity_date = c.activity_date
    left join merchants as m
        on s.merchant_id = m.merchant_id

)

select * from final
