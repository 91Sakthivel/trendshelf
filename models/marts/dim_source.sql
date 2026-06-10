{{
    config(
        materialized = 'table',
        description  = 'Static dimension describing each data source collected by collect_apis.py.'
    )
}}

/*
  One row per data source. Static — add new rows here as sources are onboarded.
  source_key = TO_HEX(MD5(lowercase source identifier)) so fact tables can
  hard-code the key with TO_HEX(MD5('kroger')) etc. without a lookup join.
*/

select TO_HEX(MD5('kroger'))         as source_key,
       'Kroger'                       as source_name,
       'Retail Price'                 as source_type,
       'Daily'                        as refresh_frequency

union all

select TO_HEX(MD5('fred'))            as source_key,
       'FRED'                         as source_name,
       'Producer Price Index'         as source_type,
       'Monthly'                      as refresh_frequency

union all

select TO_HEX(MD5('bls'))             as source_key,
       'BLS'                          as source_name,
       'Consumer Price Index'         as source_type,
       'Monthly'                      as refresh_frequency

union all

select TO_HEX(MD5('google_trends'))   as source_key,
       'Google Trends'                as source_name,
       'Search Trends'                as source_type,
       'Weekly'                       as refresh_frequency

union all

select 'SRC005'                        as source_key,
       'SerpAPI'                       as source_name,
       'Competitor Intelligence'       as source_type,
       'Weekly'                        as refresh_frequency
