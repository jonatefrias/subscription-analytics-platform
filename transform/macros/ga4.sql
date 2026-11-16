{#
  GA4 exports event parameters as a repeated key/value record. Each warehouse unnests it
  differently, so the extraction is dispatched per adapter.
    ga4_param('event_params', 'ga_session_id', 'int_value')
  value_type is one of: string_value, int_value, double_value.
#}
{% macro ga4_param(column, key, value_type) -%}
    {{ return(adapter.dispatch('ga4_param')(column, key, value_type)) }}
{%- endmacro %}

{% macro duckdb__ga4_param(column, key, value_type) -%}
    list_filter({{ column }}, x -> x.key = '{{ key }}')[1].value.{{ value_type }}
{%- endmacro %}

{% macro bigquery__ga4_param(column, key, value_type) -%}
    (select p.value.{{ value_type }} from unnest({{ column }}) as p where p.key = '{{ key }}' limit 1)
{%- endmacro %}

{% macro snowflake__ga4_param(column, key, value_type) -%}
    filter({{ column }}, x -> x:key::string = '{{ key }}')[0]:value:{{ value_type }}
{%- endmacro %}


{# GA4 event_timestamp is microseconds since the Unix epoch, in UTC. #}
{% macro micros_to_timestamp(column) -%}
    {{ return(adapter.dispatch('micros_to_timestamp')(column)) }}
{%- endmacro %}

{% macro duckdb__micros_to_timestamp(column) -%}
    make_timestamp({{ column }})
{%- endmacro %}

{% macro bigquery__micros_to_timestamp(column) -%}
    timestamp_micros({{ column }})
{%- endmacro %}

{% macro snowflake__micros_to_timestamp(column) -%}
    to_timestamp_ntz({{ column }}, 6)
{%- endmacro %}
