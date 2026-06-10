{{
    config(
        materialized = 'view',
        description  = 'Competitor product prices from SerpAPI Walmart Search API. One row per product per category per collection date.'
    )
}}

/*
  Source: serpapi_prices_raw
  Collected weekly by collect_apis.py â†’ collect_serpapi().
  Engine: walmart, store_id=2105 (Walmart Supercenter, 4122 LBJ Fwy, Dallas TX 75244).
  Prices are single-item shelf prices; price_per_unit normalises across pack sizes.
*/

with source as (

    select * from {{ source('bronze', 'serpapi_prices_raw') }}

),

staged as (

    select
        CAST(search_date AS DATE)                                         as reference_date,
        product_name,
        competitor_store,
        CAST(walmart_store_id AS STRING)                                  as walmart_store_id,
        competitor_price,
        price_per_unit,
        price_per_unit_str,
        category,
        search_query,
        'SRC005'                                                          as source_key,
        collected_at,
        CURRENT_TIMESTAMP()                                               as load_timestamp,
        -- Surrogate key: store + product + date
        TO_HEX(MD5(CONCAT(
            COALESCE(competitor_store, ''),  '||',
            COALESCE(product_name,     ''),  '||',
            CAST(search_date AS STRING)
        )))                                                               as serpapi_price_id
    from source
    where competitor_price is not null
      and competitor_price > 0

)

select * from staged

