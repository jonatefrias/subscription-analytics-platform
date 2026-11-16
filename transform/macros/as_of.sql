{# Reporting cut-off as a timestamp / date literal (see var `as_of_date`). #}
{% macro as_of_ts() -%}
    cast('{{ var("as_of_date") }} 00:00:00' as timestamp)
{%- endmacro %}

{% macro as_of_date() -%}
    cast('{{ var("as_of_date") }}' as date)
{%- endmacro %}
