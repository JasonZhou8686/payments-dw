{#- Convert an INT64 cents column to NUMERIC dollars. Usage: {{ cents_to_dollars('amount_cents') }} -#}
{% macro cents_to_dollars(column_name, precision=2) -%}
    round(safe_cast({{ column_name }} as numeric) / 100, {{ precision }})
{%- endmacro %}
