-- Override dbt's default schema-name logic.
--
-- Default behaviour in BigQuery: <target.dataset>_<custom_schema> → "bronze_bronze"
-- With this override:            <custom_schema>                   → "bronze"
--
-- If no custom schema is set on a model, fall back to the profile's dataset.

{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.dataset }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
