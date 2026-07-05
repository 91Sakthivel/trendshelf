{{
    config(
        materialized = 'view',
        description  = 'Parse-coverage audit for int_kroger_unit_price. One row per category. Ordered by ascending parse coverage so problem categories surface first.'
    )
}}

with src as (

    select * from {{ ref('int_kroger_unit_price') }}

),

agg as (

    select
        category,
        COUNT(*)                                                                  as total_items,
        COUNTIF(unit_parse_ok)                                                    as parsed_items,
        COUNTIF(NOT unit_parse_ok)                                                as failed_items,
        ROUND(100.0 * COUNTIF(unit_parse_ok) / COUNT(*), 2)                       as parse_coverage_pct,
        COUNTIF(unit_parse_ok AND kroger_unit_price_raw IS NOT NULL)              as unit_price_items,
        ROUND(
            100.0 * COUNTIF(unit_parse_ok AND kroger_unit_price_raw IS NOT NULL)
            / COUNT(*),
            2
        )                                                                         as unit_price_coverage_pct
    from src
    group by 1

)

select * from agg
order by parse_coverage_pct asc
