{{
    config(
        materialized = 'view',
        description  = 'Kroger product prices across 20 DFW stores Ã— 10 categories. One row per product per collection run.'
    )
}}

/*
  Source: kroger_prices_raw
  Data is already flat and typed by collect_apis.py â€” nested items[]/categories[]
  were unpacked during collection. price_promo is NULL when no promotion is active.
  store_city and category are added by the collector for multi-store/multi-category runs.
*/

with source as (

    select * from {{ source('bronze', 'kroger_prices_raw') }}

),

staged as (

    select
        product_id,
        upc,
        brand,
        description,
        primary_category,
        price_regular,
        price_promo,
        item_size,
        sold_by,
        store_id,
        store_city,
        category,
        search_term,
        collected_at,
        CURRENT_TIMESTAMP()                                                         as load_timestamp,
        -- Surrogate key: store + category + product (category scopes the search)
        TO_HEX(MD5(CONCAT(store_id, '||', COALESCE(category, ''), '||', product_id))) as product_key
    from source

)

select * from staged

