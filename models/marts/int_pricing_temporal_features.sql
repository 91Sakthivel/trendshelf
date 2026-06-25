{{
    config(
        materialized = 'table',
        description  = 'Temporal pricing features per store × category ordered by collection date. Lag, direction stability, consecutive run counts, volatility, and directional action eligibility. Reads fct_store_category_weekly.'
    )
}}

/*
  Grain: kroger_collection_date × store_id × category_name (same as fct_store_category_weekly).
  All dates preserved — one row per date per store per category.

  Confidence interpretation:
    collection_count = 1  → no signal (first observation, no lag)
    collection_count = 2  → weak signal (one lag available, one direction comparison)
    collection_count = 3  → usable signal (directional_action_eligible may be TRUE)
    collection_count >= 4 → stronger signal (multiple confirmations possible)

  stable_direction_count: consecutive rows ending at the current row where price_gap_direction
  matches. Uses a gaps-and-islands approach via cumulative SUM of direction change flags.
  Returns 1 on the first row of each new direction run, increments within the run.
*/

-- ── Step 1: Pull base columns from fact table ─────────────────────────────────

with base as (

    select
        kroger_collection_date,
        store_id,
        category_name,
        price_gap_pct,
        price_gap_direction
    from {{ ref('fct_store_category_weekly') }}

),

-- ── Step 2: Lag features, collection count, volatility ────────────────────────

lagged as (

    select
        kroger_collection_date,
        store_id,
        category_name,
        price_gap_pct,
        price_gap_direction,

        LAG(price_gap_pct) OVER (
            PARTITION BY store_id, category_name
            ORDER BY kroger_collection_date
        )                                                           as previous_price_gap_pct,

        LAG(price_gap_direction) OVER (
            PARTITION BY store_id, category_name
            ORDER BY kroger_collection_date
        )                                                           as previous_gap_direction,

        COUNT(*) OVER (
            PARTITION BY store_id, category_name
        )                                                           as collection_count,

        ROUND(STDDEV(price_gap_pct) OVER (
            PARTITION BY store_id, category_name
        ), 2)                                                       as price_gap_volatility

    from base

),

-- ── Step 3: Direction stability and change flag ───────────────────────────────

with_stability as (

    select
        *,

        -- gap_direction_stable: both current and previous are non-null, non-Unknown, and match.
        -- FALSE on the first row (no previous) and whenever direction flips or data is missing.
        (
            price_gap_direction     IS NOT NULL
            AND price_gap_direction != 'Unknown'
            AND previous_gap_direction IS NOT NULL
            AND previous_gap_direction != 'Unknown'
            AND price_gap_direction = previous_gap_direction
        )                                                           as gap_direction_stable,

        -- direction_change_flag: 1 at start of a new direction run, 0 within a run.
        -- Used to create island IDs via cumulative sum.
        CASE
            WHEN previous_gap_direction IS NULL
              OR price_gap_direction = 'Unknown'
              OR previous_gap_direction = 'Unknown'
              OR price_gap_direction != previous_gap_direction   THEN 1
            ELSE 0
        END                                                         as direction_change_flag

    from lagged

),

-- ── Step 4: Island IDs — cumulative sum of change flags ───────────────────────
-- Each time direction changes, island_id increments. Rows within the same
-- consecutive direction run share the same island_id.

with_island as (

    select
        *,
        SUM(direction_change_flag) OVER (
            PARTITION BY store_id, category_name
            ORDER BY kroger_collection_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )                                                           as island_id

    from with_stability

)

-- ── Final: assemble all 8 temporal feature columns ───────────────────────────

select
    kroger_collection_date,
    store_id,
    category_name,

    -- (1) Lag of gap value
    previous_price_gap_pct,

    -- (2) Lag of direction label
    previous_gap_direction,

    -- (3) Core temporal gate: TRUE when direction held from prior date
    gap_direction_stable,

    -- (4) Total collection count for this store × category (window, not just to current row)
    collection_count,

    -- (5) Consecutive rows in the current direction run ending at this row
    ROW_NUMBER() OVER (
        PARTITION BY store_id, category_name, island_id
        ORDER BY kroger_collection_date
    )                                                               as stable_direction_count,

    -- (6) Change in gap since previous collection
    ROUND(price_gap_pct - previous_price_gap_pct, 2)               as price_gap_change_pct,

    -- (7) Price gap volatility across all collected dates for this store × category
    price_gap_volatility,

    -- (8) Eligible for directional action: need ≥3 collections AND stable direction
    -- With 1 date: no lag. With 2 dates: one comparison available but not yet confirmed.
    -- With 3+ dates AND direction stable: signal is usable.
    (collection_count >= 3 AND gap_direction_stable IS TRUE)        as directional_action_eligible

from with_island
