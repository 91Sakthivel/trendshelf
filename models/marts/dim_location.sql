{{
    config(
        materialized = 'table',
        description  = 'Store/location dimension derived from distinct store IDs and city labels in Kroger staging data.'
    )
}}

/*
  One row per distinct store_id observed in stg_kroger_prices.
  store_city carries the human label set in collect_apis.py KROGER_STORES list,
  e.g. "Dallas - Capitol Ave". City is extracted as the part before " - ".
*/

with source as (

    select distinct store_id, store_city
    from {{ ref('stg_kroger_prices') }}
    where store_id is not null

)

select
    TO_HEX(MD5(store_id))                            as location_key,
    store_id,
    CONCAT('Kroger ', COALESCE(store_city, store_id)) as store_name,
    -- Extract city from "City - Branch" label; single-name cities (e.g. "Denton") returned as-is
    SPLIT(COALESCE(store_city, store_id), ' - ')[SAFE_OFFSET(0)] as city,
    'TX'                                              as state,
    'South'                                           as region
from source
