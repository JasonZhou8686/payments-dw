{% snapshot merchants_snapshot %}

{{
    config(
        unique_key='merchant_id',
        strategy='timestamp',
        updated_at='updated_at',
        invalidate_hard_deletes=true
    )
}}

select * from {{ source('payments', 'merchants') }}

{% endsnapshot %}
