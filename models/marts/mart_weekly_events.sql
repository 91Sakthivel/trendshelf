{{
    config(
        materialized = 'view',
        description  = 'Week-over-week pricing event feed. Grain: event_type × store_id × category_name, anchored to MAX(kroger_collection_date). Three event types: Gap Flip (position band crossed), Big Move (|Δgap| ≥ 10pp), New Sustained (streak first hits 3 weeks). All qualifying rows returned; UI filters by event_rank and competitor_reliability.'
    )
}}

/*
  Events compare "this week" to "last week" only.
  int_pricing_temporal_features supplies all lag/streak columns.
  fct_store_category_weekly supplies competitor_reliability (not surfaced in temporal model).
  Both are joined at the same grain: kroger_collection_date × store_id × category_name.

  event_rank ordering:
    Gap Flip, Big Move → ABS(price_gap_change_pct) DESC (largest move ranks first)
    New Sustained      → ABS(price_gap_pct)        DESC (widest gap ranks first)
*/

-- ── Anchor: latest Kroger collection date ─────────────────────────────────────

with latest_date as (

    select MAX(kroger_collection_date) as latest_kroger_date
    from {{ ref('fct_store_category_weekly') }}

),

-- ── Base: this-week rows only, with all features and reliability label ─────────

base as (

    select
        tf.kroger_collection_date,
        tf.store_id,
        tf.category_name,
        f.price_gap_pct,
        tf.price_gap_change_pct,
        tf.price_position,
        tf.previous_price_position,
        tf.stable_direction_count,
        f.competitor_reliability
    from {{ ref('int_pricing_temporal_features') }} tf
    join {{ ref('fct_store_category_weekly') }} f
      on tf.kroger_collection_date = f.kroger_collection_date
     and tf.store_id               = f.store_id
     and tf.category_name          = f.category_name
    cross join latest_date ld
    where tf.kroger_collection_date = ld.latest_kroger_date

),

-- ── Event type 1: Gap Flip ────────────────────────────────────────────────────
-- price_position crossed a CV-calibrated band boundary this week.
-- Both current and previous positions must be non-null and non-Unknown.

gap_flip as (

    select
        kroger_collection_date,
        store_id,
        category_name,
        'Gap Flip'                                                  as event_type,
        CONCAT(
            'Position changed: ', previous_price_position,
            ' → ', price_position
        )                                                           as event_detail,
        price_gap_pct,
        price_gap_change_pct,
        price_position,
        previous_price_position,
        stable_direction_count,
        competitor_reliability,
        ROW_NUMBER() OVER (
            ORDER BY ABS(price_gap_change_pct) DESC NULLS LAST
        )                                                           as event_rank
    from base
    where price_position          <> previous_price_position
      and price_position          NOT IN ('Unknown')
      and previous_price_position IS NOT NULL
      and previous_price_position <> 'Unknown'
      and ABS(price_gap_change_pct) <= {{ var('reliability_low_gap_threshold') }}

),

-- ── Event type 2: Big Move ────────────────────────────────────────────────────
-- Absolute gap shift ≥ 10 percentage points week-over-week.
-- Fires regardless of whether a band boundary was crossed.
-- price_gap_change_pct is NULL on the first collection, so first-date rows
-- are naturally excluded by the ABS(...) >= 10 predicate.

big_move as (

    select
        kroger_collection_date,
        store_id,
        category_name,
        'Big Move'                                                  as event_type,
        CONCAT(
            'Gap moved ',
            CASE WHEN price_gap_change_pct >= 0 THEN '+' ELSE '' END,
            CAST(ROUND(price_gap_change_pct, 1) AS STRING),
            'pp this week'
        )                                                           as event_detail,
        price_gap_pct,
        price_gap_change_pct,
        price_position,
        previous_price_position,
        stable_direction_count,
        competitor_reliability,
        ROW_NUMBER() OVER (
            ORDER BY ABS(price_gap_change_pct) DESC
        )                                                           as event_rank
    from base
    where ABS(price_gap_change_pct) >= 10
      and ABS(price_gap_change_pct) <= {{ var('reliability_low_gap_threshold') }}

),

-- ── Event type 3: New Sustained ───────────────────────────────────────────────
-- Fires exactly once when a direction streak first reaches 3 consecutive collections.
-- stable_direction_count = 3 does not re-fire at 4, 5, ... — promotion happens once.

new_sustained as (

    select
        kroger_collection_date,
        store_id,
        category_name,
        'New Sustained'                                             as event_type,
        CONCAT(
            price_position,
            ' streak reached 3 consecutive weeks'
        )                                                           as event_detail,
        price_gap_pct,
        price_gap_change_pct,
        price_position,
        previous_price_position,
        stable_direction_count,
        competitor_reliability,
        ROW_NUMBER() OVER (
            ORDER BY ABS(price_gap_pct) DESC NULLS LAST
        )                                                           as event_rank
    from base
    where stable_direction_count = 3

),

final as (

    select * from gap_flip
    UNION ALL
    select * from big_move
    UNION ALL
    select * from new_sustained

)

select * from final
order by event_type, event_rank
