# TrendShelf — Threshold and Prior Decisions

## 1. Purpose

This file records where the judgement-call numbers in TrendShelf came from. It does not record every constant — structural constants such as 0, 1, or 100 are not listed. The focus is on values that influence a score, label, API call, or action recommendation, where a different reasonable choice would produce a materially different result. Each entry states the source of the value and the conditions under which it should be revisited.

---

## 2. Category sensitivity priors

The table below is verbatim from the `category_elasticity` CTE in `models/marts/mart_pricing_intelligence.sql`. These values are **analyst-set priors** reflecting general grocery category behaviour based on published CPG and retail industry knowledge. They are **not measured from TrendShelf data**. TrendShelf does not have sales velocity or units-sold data; replacing these priors with empirically derived price sensitivity estimates would require time-series sales/units data that the project does not currently collect.

The priors are used in two places in `mart_pricing_intelligence.sql`:

- `category_sensitivity_tier` gates the Hold Premium and Review Price Reduction cascade branches (values `'Low'`, `'Medium'`, `'High'` control elasticity direction).
- `category_premium_tolerance_prior_score` is one of five inputs to `pricing_power_score` with weight 0.20. It shifts pricing power upward for categories where consumers historically tolerate premium pricing relative to mass-market retailers.

| Category | Sensitivity tier | Premium tolerance prior score |
|---|---|---|
| beverages | Low | 70 |
| snacks | Medium | 55 |
| dairy | High | 30 |
| frozen foods | High | 35 |
| breakfast cereal | Medium | 55 |
| meat seafood | High | 30 |
| produce | High | 25 |
| personal care | Low | 75 |
| household | High | 35 |
| coffee tea | Low | 80 |

**Tier interpretation:** High = price-sensitive (consumers readily substitute on price); Low = price-tolerant (brand or quality justifies Kroger premium over Walmart). Medium is intermediate.

**When to revisit:** If a category is added to `config.py:CATEGORIES` it must also be added to this STRUCT; the singular test `tests/assert_elasticity_prior_coverage.sql` will fail if it is not. Values should be recalibrated once sales/units data is available.

---

## 3. Externalized thresholds (dbt_project.yml vars)

These values are externalized because they appear in multiple models or are expected to be tuned as more data accumulates. The current values are as of 2026-07-23.

| Var name | Value | Controls |
|---|---|---|
| `opp_weight_demand` | 0.25 | overall_opportunity_score weight for demand |
| `opp_weight_expansion` | 0.20 | overall_opportunity_score weight for expansion |
| `opp_weight_pricing` | 0.20 | overall_opportunity_score weight for pricing power |
| `opp_weight_confidence` | 0.15 | overall_opportunity_score weight for confidence |
| `opp_weight_risk` | 0.10 | overall_opportunity_score weight for risk |
| `opp_weight_margin` | 0.10 | overall_opportunity_score weight for margin |
| `opp_tier_prime` | 75 | Opportunity tier: Prime threshold |
| `opp_tier_solid` | 55 | Opportunity tier: Solid threshold |
| `opp_tier_watch` | 35 | Opportunity tier: Watch threshold |
| `demand_high_threshold` | 65 | Demand signal High cutoff |
| `demand_medium_threshold` | 45 | Demand signal Medium cutoff |
| `confidence_high` | 75 | Confidence level HIGH cutoff |
| `confidence_medium` | 50 | Confidence level MEDIUM cutoff |
| `investigate_confidence_threshold` | 45 | INVESTIGATE gate: confidence below this |
| `avoid_margin_pressure_threshold` | 80 | AVOID gate: margin pressure above this |
| `avoid_markdown_safety_threshold` | 40 | AVOID gate: markdown safety below this |
| `expand_readiness_threshold` | 80 | EXPAND gate: readiness above this |
| `expand_confidence_threshold` | 70 | EXPAND gate: confidence above this |
| `expand_margin_threshold` | 70 | Review Price Increase gate: pricing power minimum |
| `margin_pressure_avoid_threshold` | 65 | Review Price Increase gate: margin pressure maximum |
| `pricing_power_hold_threshold` | 70 | Hold Premium gate: pricing power minimum |
| `pricing_power_strong_threshold` | 75 | Hold Premium gate: bypass relevance check |
| `reduce_price_min_gap_pct` | 10 | Review Price Reduction gate: minimum adjusted gap (%) |
| `markdown_safety_full_threshold` | 60 | Full vs Partial cut boundary |
| `competitive_threat_threshold` | 70 | Protect Price gate: threat above this blocks |
| `cv_multiplier` | 0.16 | Price band width: CV × multiplier |
| `min_price_gap_threshold` | 8.0 | Price band floor (%) |
| `max_price_gap_threshold` | 25.0 | Price band ceiling (%) |
| `reliability_low_gap_threshold` | 50.0 | Gap above this → Low reliability |
| `reliability_medium_gap_threshold` | 25.0 | Gap above this → Medium reliability |
| `reliability_min_competitor_count` | 10 | Fewer competitor products → Low reliability |
| `max_competitor_staleness_days` | 14 | Competitor price older than this → Low reliability |
| `confidence_smoothing_k` | 15.0 | Laplace smoothing parameter for price_gap_confidence_weight |
| `demand_slope_rising_threshold` | 0.3 | OLS slope-to-noise ratio for demand_state classification |
| `directional_established_min_dates` | 4 | Collections needed to graduate from Provisional to Persistent |
| `threshold_config_version` | 'v4_cv_calibrated' | Version tag stamped on output rows |

---

## 4. Scoring formula weights — deliberately NOT externalized

The per-formula weights (e.g. markdown_safety_score's 0.45/0.30/0.25, pricing_power_score's 0.30/0.20/0.20/0.15/0.15, and the five other composite scores) are kept inline in each model rather than moved to dbt vars.

The reason: a weight belongs next to the formula it governs. A reader looking at the SQL sees both the components and their relative importance together; moving them to a config file requires two files to understand one computation. Additionally, changing a weight without simultaneously reviewing the adjacent formula and its neighbours is error-prone — the inline placement creates natural friction that prevents casual tuning of unvalidated knobs. These weights should only change when a specific empirical finding justifies it, at which point the formula and weight change together in the same commit.

---

## 5. Naming changelog

### Commit 875822a — naming-honesty pass (string values only)

Output string values were renamed to reflect what the system actually recommends rather than the bare action. No formula, threshold, or cascade logic changed.

| Old value | New value | Column |
|---|---|---|
| `'Reduce Price'` | `'Review Price Reduction'` | `mart_pricing_intelligence.recommended_price_action` |
| `'Raise Price'` | `'Review Price Increase'` | `mart_pricing_intelligence.recommended_price_action` |
| `'3 Wk Streak'` (or prior name) | `'3-Collection Streak'` | `mart_weekly_events.event_type` |
| prior directional value | `'Persistent'` | `mart_pricing_intelligence.directional_signal_confidence` |

### Commit 2a — column renames (field names only)

Internal column names were renamed to be self-describing. No score value, formula, weight, threshold, or cascade condition changed. The underlying STRUCT values (tier strings and prior scores) are identical.

| Old name | New name | Files |
|---|---|---|
| `elasticity_tier` | `category_sensitivity_tier` | `mart_pricing_intelligence.sql`, `schema.yml`, `dashboard/queries.py`, `dashboard/app.py` |
| `premium_tolerance_score` | `category_premium_tolerance_prior_score` | `mart_pricing_intelligence.sql`, `dashboard/queries.py`, `dashboard/app.py` |

---

## 6. Open item — CASE branch count vs accepted_values list

Verified at time of writing (2026-07-23):

**`directional_signal_confidence`** (`mart_pricing_intelligence.sql`, actioned CTE):
CASE branches: `'Insufficient'`, `'Unreliable'`, `'Persistent'`, `'Provisional'` = **4 branches**.
`accepted_values` list in `schema.yml`: `['Insufficient', 'Unreliable', 'Persistent', 'Provisional']` = **4 values**.
Result: counts match. ✓

**`event_type`** (`mart_weekly_events.sql`):
Literal strings assigned per CTE: `'Gap Flip'` (gap_flip CTE), `'Big Move'` (big_move CTE), `'3-Collection Streak'` (new_sustained CTE) = **3 values**.
`accepted_values` list in `schema.yml`: `['Gap Flip', 'Big Move', '3-Collection Streak']` = **3 values**.
Result: counts match. ✓
