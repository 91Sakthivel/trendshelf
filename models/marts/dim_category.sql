{{
    config(
        materialized = 'table',
        description  = 'Product category dimension derived from the 10 search-term categories used in multi-store Kroger collection.'
    )
}}

/*
  One row per distinct category search term observed in stg_kroger_prices.
  "category" is the explicit search label from CATEGORIES list in collect_apis.py
  (e.g. "beverages", "snacks"), not Kroger's internal primary_category taxonomy.
*/

with source as (

    select distinct
        COALESCE(category, 'Unknown') as category_name
    from {{ ref('stg_kroger_prices') }}

)

select
    TO_HEX(MD5(category_name))  as category_key,
    category_name,
    CASE category_name
        WHEN 'beverages'        THEN 'Food & Beverage'
        WHEN 'snacks'           THEN 'Food & Beverage'
        WHEN 'dairy'            THEN 'Food & Beverage'
        WHEN 'frozen foods'     THEN 'Food & Beverage'
        WHEN 'breakfast cereal' THEN 'Food & Beverage'
        WHEN 'meat seafood'     THEN 'Food & Beverage'
        WHEN 'produce'          THEN 'Food & Beverage'
        WHEN 'personal care'    THEN 'Health & Beauty'
        WHEN 'household'        THEN 'Household'
        WHEN 'coffee tea'       THEN 'Food & Beverage'
        ELSE 'General'
    END                          as parent_category
from source
