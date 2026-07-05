{{
    config(
        materialized = 'view',
        description  = 'Kroger products with parsed unit-price fields. One row per source row from stg_kroger_prices. Failed parses surface nulls and a typed reason — no rows are dropped.'
    )
}}

with src as (

    select * from {{ ref('stg_kroger_prices') }}

),

-- Normalise to lowercase; collapse NULL and empty-string into NULL
lowered as (

    select
        *,
        NULLIF(LOWER(TRIM(item_size)), '') as _size_lc
    from src

),

-- Run all REGEXP operations in one pass to avoid repeating the COALESCE wrapper
extracted as (

    select
        *,

        -- ── Multipack detector: "N <descriptor> / X <unit>"  e.g. "24 bottles / 16.9 fl oz"
        REGEXP_CONTAINS(
            COALESCE(_size_lc, ''),
            r'^\d+\s+[a-z][a-z\s]*\s*/\s*[\d.]+\s+[a-z]'
        )                                                                   as _is_mp,

        -- Multipack: pack count  (N)
        SAFE_CAST(
            REGEXP_EXTRACT(COALESCE(_size_lc, ''), r'^(\d+)\s+[a-z]')
        AS INT64)                                                            as _mp_pack_count,

        -- Multipack: descriptor word(s) between N and "/"  — used to detect ambiguous unit
        TRIM(REGEXP_EXTRACT(
            COALESCE(_size_lc, ''),
            r'^\d+\s+([a-z][a-z\s]*?)\s*/'
        ))                                                                   as _mp_descriptor,

        -- Multipack: per-unit quantity  (X)
        SAFE_CAST(
            REGEXP_EXTRACT(COALESCE(_size_lc, ''), r'/\s*([\d.]+)\s+[a-z]')
        AS NUMERIC)                                                          as _mp_qty,

        -- Multipack: unit string after X
        TRIM(REGEXP_EXTRACT(
            COALESCE(_size_lc, ''),
            r'/\s*[\d.]+\s+([a-z][a-z\s]*)$'
        ))                                                                   as _mp_unit_raw,

        -- ── Single-pack: "X <unit>"  e.g. "12 fl oz", "1.5 l"
        SAFE_CAST(
            REGEXP_EXTRACT(COALESCE(_size_lc, ''), r'^([\d.]+)\s+[a-z]')
        AS NUMERIC)                                                          as _sp_qty,

        -- Single-pack: unit string after X
        TRIM(REGEXP_EXTRACT(
            COALESCE(_size_lc, ''),
            r'^[\d.]+\s+([a-z][a-z\s]*)$'
        ))                                                                   as _sp_unit_raw

    from lowered

),

-- Classify each row into a branch and resolve the raw unit to a canonical token
classified as (

    select
        *,

        -- Branch (first-match wins)
        CASE
            WHEN _size_lc IS NULL
                THEN 'missing_item_size'
            -- Ambiguous when descriptor is itself a recognised unit word
            -- e.g. "8 oz / 16 oz" — could mean many things; flag rather than guess
            WHEN _is_mp
             AND _mp_descriptor IN (
                'fl oz','floz','fluid ounce','fluid ounces',
                'oz','ounce','ounces',
                'lb','lbs','pound','pounds',
                'g','gram','grams',
                'ml',
                'l','liter','liters',
                'ct','count','pack','pk'
             )
                THEN 'ambiguous_multi_unit'
            WHEN _is_mp
                THEN 'multipack'
            WHEN _sp_qty IS NOT NULL AND _sp_unit_raw IS NOT NULL
                THEN 'single'
            ELSE 'unknown'
        END                                                                  as _branch,

        -- Canonical unit mapping (applied to whichever branch was active)
        CASE COALESCE(CASE WHEN _is_mp THEN _mp_unit_raw ELSE _sp_unit_raw END, '')
            WHEN 'fl oz'          THEN 'fl_oz'
            WHEN 'floz'           THEN 'fl_oz'
            WHEN 'fluid ounce'    THEN 'fl_oz'
            WHEN 'fluid ounces'   THEN 'fl_oz'
            WHEN 'oz'             THEN 'oz'
            WHEN 'ounce'          THEN 'oz'
            WHEN 'ounces'         THEN 'oz'
            WHEN 'lb'             THEN 'lb'
            WHEN 'lbs'            THEN 'lb'
            WHEN 'pound'          THEN 'lb'
            WHEN 'pounds'         THEN 'lb'
            WHEN 'g'              THEN 'g'
            WHEN 'gram'           THEN 'g'
            WHEN 'grams'          THEN 'g'
            WHEN 'ml'             THEN 'ml'
            WHEN 'l'              THEN 'l'
            WHEN 'liter'          THEN 'l'
            WHEN 'liters'         THEN 'l'
            WHEN 'ct'             THEN 'ct'
            WHEN 'count'          THEN 'ct'
            WHEN 'pack'           THEN 'ct'
            WHEN 'pk'             THEN 'ct'
            ELSE NULL
        END                                                                  as _unit_canonical

    from extracted

),

-- Consolidate multipack / single qty into a single column to avoid repeating CASE
resolved as (

    select
        *,
        CASE _branch
            WHEN 'multipack' THEN CAST(_mp_qty AS NUMERIC)
            WHEN 'single'    THEN _sp_qty
            ELSE NULL
        END as _qty
    from classified

),

final as (

    select
        -- ── All source columns ────────────────────────────────────────────────
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
        load_timestamp,
        product_key,

        -- ── Parsed size dimensions ────────────────────────────────────────────
        -- size_qty: the per-unit quantity  (16.9 from "24 bottles / 16.9 fl oz")
        _qty                                                                 as size_qty,

        -- size_unit: canonical unit token; NULL on any parse failure
        CASE WHEN _branch IN ('multipack', 'single') THEN _unit_canonical
             ELSE NULL
        END                                                                  as size_unit,

        -- pack_count: number of identical units in the package (default 1)
        CAST(
            CASE _branch
                WHEN 'multipack' THEN _mp_pack_count
                ELSE 1
            END
        AS INT64)                                                             as pack_count,

        -- ── Computed unit price ───────────────────────────────────────────────
        -- price_regular / (pack_count × size_qty); NULL on any failure
        CASE
            WHEN _branch IN ('multipack', 'single')
             AND _unit_canonical IS NOT NULL
             AND _qty > 0
             AND price_regular IS NOT NULL
                THEN CAST(
                    SAFE_DIVIDE(
                        price_regular,
                        CASE _branch
                            WHEN 'multipack'
                                THEN CAST(_mp_pack_count AS NUMERIC) * _qty
                            WHEN 'single'
                                THEN _qty
                        END
                    )
                AS NUMERIC)
            ELSE NULL
        END                                                                  as kroger_unit_price_raw,

        -- ── Parse quality ─────────────────────────────────────────────────────
        -- TRUE only when all three conditions hold: qty>0, unit resolved, price present
        (
            _branch IN ('multipack', 'single')
            AND _unit_canonical IS NOT NULL
            AND _qty > 0
            AND price_regular IS NOT NULL
        )                                                                     as unit_parse_ok,

        -- Specific failure reason; exactly one of the seven enumerated values
        CASE
            WHEN _size_lc IS NULL
                THEN 'missing_item_size'
            WHEN _branch = 'ambiguous_multi_unit'
                THEN 'ambiguous_multi_unit'
            WHEN _branch = 'unknown'
                THEN 'unknown_size_format'
            WHEN _branch IN ('multipack', 'single') AND _unit_canonical IS NULL
                THEN 'unsupported_unit'
            WHEN _branch IN ('multipack', 'single') AND _unit_canonical IS NOT NULL AND _qty <= 0
                THEN 'zero_or_invalid_qty'
            WHEN _branch IN ('multipack', 'single') AND _unit_canonical IS NOT NULL AND _qty > 0
             AND price_regular IS NULL
                THEN 'missing_price'
            WHEN _branch IN ('multipack', 'single') AND _unit_canonical IS NOT NULL AND _qty > 0
             AND price_regular IS NOT NULL
                THEN 'parsed_ok'
            ELSE 'unknown_size_format'
        END                                                                   as unit_parse_reason

    from resolved

)

select * from final
