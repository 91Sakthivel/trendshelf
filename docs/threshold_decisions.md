# TrendShelf — Threshold and Prior Decisions

## 1. Purpose

This file records where the judgement-call numbers in TrendShelf came from. It does not record every constant — structural constants such as 0, 1, or 100 are not listed. The focus is on values that influence a score, label, API call, or action recommendation, where a different reasonable choice would produce a materially different result. Each entry states the source of the value and the conditions under which it should be revisited.

---

## 2. Category sensitivity priors

The table below is verbatim from the `category_elasticity` CTE in `models/marts/mart_pricing_intelligence.sql`. These values are **analyst-set priors** reflecting general grocery category behaviour based on published CPG and retail industry knowledge. They are **not measured from TrendShelf data**. TrendShelf does not have sales velocity or units-sold data; replacing these priors with empirically derived price sensitivity estimates would require time-series sales/units data that the project does not currently collect.

The priors are used in two places in `mart_pricing_intelligence.sql`:

- `category_sensitivity_tier` gates the Hold Premium and Review Price Reduction cascade branches (values `'Low'`, `'Medium'`, `'High'` control elasticity direction).
- `category_premium_tolerance_prior_score` is one of five inputs to `premium_support_proxy_score` with weight 0.20. It shifts pricing power upward for categories where consumers historically tolerate premium pricing relative to mass-market retailers.

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

The per-formula weights (e.g. markdown_safety_score's 0.45/0.30/0.25, premium_support_proxy_score's 0.30/0.20/0.20/0.15/0.15, and the five other composite scores) are kept inline in each model rather than moved to dbt vars.

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

### Commit 3 — column rename (`pricing_power_score`)

Reason: the score measures whether available signals SUPPORT holding a premium; it does not measure true pricing power, which would require sales and margin data. No formula, weight, threshold, or cascade condition changed — only the column name.

| Old name | New name | Files |
|---|---|---|
| `pricing_power_score` | `premium_support_proxy_score` | `mart_pricing_intelligence.sql`, `mart_action_queue.sql`, `schema.yml`, `dashboard/queries.py`, `dashboard/app.py`, `docs/threshold_decisions.md`, `docs/scoring_methodology.md` |

### Commit 4 — column rename (`margin_pressure_risk`) + user-facing wording

Reason: the score infers margin pressure by comparing Kroger's own shelf-price trend to the FRED PPI index. No cost, margin, or COGS figure is read anywhere. "proxy" marks it as inferred, matching `premium_support_proxy_score`. No formula, weight, threshold, or cascade condition changed — only the column name and three user-facing strings.

| Old name | New name | Files |
|---|---|---|
| `margin_pressure_risk` | `margin_pressure_proxy_score` | `mart_price_margin_scores.sql`, `mart_action_queue.sql`, `mart_confidence_layer.sql`, `mart_expansion_readiness.sql`, `mart_pricing_intelligence.sql`, `schema.yml`, `docs/scoring_methodology.md` |

**What `margin_pressure_proxy_score` uses and does not use:**
- Uses: Kroger's own retail shelf-price trend (`AVG(price_regular)` from `stg_kroger_prices`, month over month) and the FRED Producer Price Index trend (`stg_fred_ppi`, an external industry-wide macro series).
- Does not use: supplier cost, COGS, or any observed margin figure. Nothing in this model reads an actual cost or margin number for the brand or product — the score is a rule-based classification of whether retail price kept pace with a macro cost proxy, not a measurement of margin.

**User-facing wording changed (zero numeric impact, same CASE conditions):**
- `mart_expansion_readiness.sql` — the `'FIX MARGINS'` recommendation string no longer says "negotiate COGS" (implies observed supplier cost data that doesn't exist). Now: "Shelf price has not kept pace with rising category input costs (inferred from industry price indices, not observed supplier costs) — review cost position before expanding."
- `mart_action_queue.sql:316` (action_description) — "margin pressure (N/100)" → "cost-pressure indicator (N/100)".
- `mart_action_queue.sql:402` (action_justification) — "margins critically squeezed" → "cost-pressure indicator elevated"; "margin pressure N" → "cost-pressure indicator N".

**Left unchanged, deliberately:**
- `dbt_project.yml` var names `avoid_margin_pressure_threshold` and `margin_pressure_avoid_threshold`, and their mirrors in `README.md` — these are threshold var identifiers, a separate naming surface from the column itself.
- `docs/session_notes_batch3_hardening.md` and notebook files — dated historical records, not live reference docs.
- `mart_action_queue.sql:455` — the `reason_code` literal `'PROMO_RISK_MARGIN_PRESSURE'`. This is a machine token (a `reason_code`, not display text) with no user-facing consumer; left as-is.

**Noted duplication:** `mart_pricing_intelligence.sql:435` re-applies `COALESCE(margin_pressure_proxy_score, 30)` on top of the producer's own NULL handling in `mart_price_margin_scores.sql:189` (which already resolves NULL inputs to 30 before the value ever leaves that model). The column can never actually be NULL by the time it reaches `mart_pricing_intelligence`, so this second COALESCE is inert — not a bug, just redundant defensive code. Not changed as part of this rename (formula/logic untouched by instruction).

**Open finding — STEP 3 measurement (2026-07-23):** The "healthy" branch (`GREATEST(0, 30 − Δretail_price / 5.0)`, where `Δretail_price = retail_price − retail_price_1m_ago`) currently produces scores confined to **29.52–30.00** across all 71 rows that reach it (55 distinct rounded values, but all within a 0.48-point band out of the score's 0–100 range), even though the underlying `Δretail_price` ranges from $0.01 to $2.40 — a 200× spread in input collapsed to <0.5% of output range by the `/5.0` divisor. Branch membership overall: 329 rows `BRANCH_55_COMPRESSION`, 71 rows `BRANCH_HEALTHY`, 0 rows `BRANCH_80_SQUEEZE`, 0 rows `BRANCH_40_COST_RISING`, 0 rows `NULL_FALLBACK_30` (determined by reconstructing the producer's own `retail_price_1m_ago` / `ppi_1m_ago` LAG logic outside the model and reapplying the identical CASE predicates; verified exact — 0 mismatches against the live `margin_pressure_risk` output across all 400 rows before this rename's rebuild). Not fixed — flagged for a future pass once more months of Kroger data reduce the single-month-lag skew (329 of 400 rows currently have no prior month at all and fall trivially into branch 55).

### Commit 5 — string literal rename (`score_version`)

Reason: the scoring logic is a calibrated heuristic cascade (rule-based CASE branches with analyst-set thresholds and weights), not a fitted statistical model. `'v4_statistical_calibration'` overstated what the engine does. The `v4_` prefix is kept — this pass changed terminology only, not the scoring logic, formulas, weights, thresholds, or cascade conditions in any of the 7 marts.

| Old value | New value | Files |
|---|---|---|
| `'v4_statistical_calibration'` | `'v4_robust_heuristic_calibration'` | `mart_pricing_intelligence.sql` (score_version alias + config description + header comment), `mart_action_queue.sql`, `mart_confidence_layer.sql`, `mart_demand_gap_scores.sql`, `mart_expansion_readiness.sql`, `mart_price_margin_scores.sql`, `mart_shelfrisk_scores.sql`, `models/schema.yml`, `dashboard/app.py` (fallback string, 2 sites) |

**Left unchanged, deliberately:** `docs/session_notes_v4_pricing.md:16` — a dated historical record of the v4 rollout, not a live reference doc.

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

---

## 7. FRED PPI — single-series contract and series identity finding

Covers commit `44afed8` (FRED single-series contract at the staging layer), which shipped without a doc entry.

### 7.1 The single-series staging contract

`fred_ppi_raw` can carry more than one FRED series — the collector can pull an additional series without switching scoring to it. `stg_fred_ppi.sql` filters to exactly one series, named by the var `scoring_ppi_series_id`, before any downstream model sees the data:

```sql
where observation_date >= '2025-01-01'
  and series_id = '{{ var("scoring_ppi_series_id") }}'
```

This is the single point of truth for "which FRED series does scoring use." The alternative — a `series_id` filter repeated in every consumer model — was rejected because it means the same assumption is encoded in five places instead of one; a future model added without remembering the filter would silently reintroduce cross-series contamination. Switching which series scoring uses becomes a one-line var change with no model edits, because every downstream model already assumes (and, with this filter, is guaranteed) a single-series input.

### 7.2 Consumer sites that carry no local filter, and what a second series would have done to each

None of the following files reference `series_id` — they rely entirely on the staging contract:

| File | Mechanism | Failure mode with a second, unfiltered series |
|---|---|---|
| `fact_market_signals.sql` (`fred`, `fred_as_of` CTEs) | Two-step as-of join, no `series_id` predicate | **Fan-out.** The final join (`f.reference_month = fa.fred_month`) would match one row per series for the same month, doubling every row in the `final` CTE and every mart built on it. |
| `mart_price_margin_scores.sql` (`ppi_as_of` CTE) | Same as-of join pattern | **Fan-out**, identical mechanism to `fact_market_signals`. |
| `mart_shelfrisk_scores.sql` (`ppi_lag_monthly` CTE) | `LAG(ppi_value, 1) OVER (ORDER BY month)`, no `PARTITION BY` | **Cross-series LAG.** With two series interleaved in month order, `LAG` would compare one series' value against the other's — a silently wrong month-over-month delta, not a fan-out. |
| `int_macro_trend_features.sql` (`ppi_windowed` CTE) | `LAG(ppi_value, 12)` plus two rolling `AVG(...) OVER (ORDER BY month ROWS BETWEEN ...)` windows, no `PARTITION BY` | **Cross-series LAG/window**, same mechanism as `mart_shelfrisk_scores.sql`, higher blast radius: feeds `ppi_trend_direction`, `normalized_ppi_growth_score`, and `ppi_3mo_trend` into `fact_market_signals`, propagating to every downstream mart. |

`mart_confidence_layer.sql`'s FRED freshness line (`MAX(collected_at)`, `COUNT(*)` from `stg_fred_ppi`) and `dashboard/queries.py`'s direct `fred_ppi_raw` read were left untouched — both answer "did the collector run," not a scoring question, and the confidence-layer one inherits the staging fix for free since it already reads through `stg_fred_ppi`.

### 7.3 Guard tests

- **`tests/assert_ppi_series_resolves.sql`** — fails if `stg_fred_ppi` returns zero rows, i.e. `scoring_ppi_series_id` matches nothing in `fred_ppi_raw` (typo, wrong ID, discontinued series, or a collector regression). Proven: pointing the var at a nonexistent series ID produced FAIL 1; restoring the real ID produced PASS.
- **`tests/assert_ppi_series_coverage.sql`** — fails if `stg_fred_ppi` has fewer than `min_ppi_monthly_rows` (= **13**) monthly rows. Proven: overriding the threshold to 20 against the live 16-row table produced FAIL 1; the real threshold of 13 produced PASS.
- **N = 13, reasoning:** `int_macro_trend_features.sql`'s `ppi_yoy_value = LAG(ppi_value, 12)` needs 13 rows of history (12 preceding plus the current row) for even the most recent month to produce a non-null year-over-year comparison. Below 13, that entire feature is unconditionally NULL for every row — the most demanding requirement of any current consumer (LAG 1/3/6 in `mart_price_margin_scores.sql` need far fewer rows).
- **Current headroom:** 16 rows live against a floor of 13 — 3 months of slack. This widens by one every month the collector's 24-month rolling pull advances without the series being discontinued or the pull window shrinking; it does not widen on its own without continued collection.
- **Rejected guard: `count(distinct series_id) > 1`.** This was the first design considered and discarded — once the staging `WHERE series_id = ...` clause exists, `stg_fred_ppi` can never expose more than one series by construction, so this test would assert exactly what the filter already guarantees and could never fail. It tests the mechanism's own tautology, not a real failure mode.
- **`tests/assert_fred_ppi_raw_no_duplicate_months.sql`** — fails if `fred_ppi_raw` (the source, not `stg_fred_ppi`) has more than one row for the same `(series_id, observation_date)`. Same "test the thing that can actually change" reasoning as the rejected guard above: `stg_fred_ppi` now dedupes via `QUALIFY ROW_NUMBER() OVER (PARTITION BY series_id, observation_date ORDER BY collected_at DESC) = 1`, so testing the model itself would be circular — the `QUALIFY` guarantees it can never fail there. Testing the raw source instead catches a real regression (e.g. `_upload` switching from `WRITE_TRUNCATE` to `WRITE_APPEND`, or gaining a partition decorator) at the point where it would first appear. Proven: temporarily changing the test's own comparison to `having count(*) >= 1` (matching every existing row, since duplicates don't currently exist in live data) produced FAIL 24; reverting to `> 1` produced PASS.
- **Why dedup was added even though today's collector can't produce duplicates:** `_upload` (`collect_apis.py`) uses `WRITE_TRUNCATE` against an undecorated destination, replacing the whole `fred_ppi_raw` table on every call rather than appending — confirmed live: 24 rows, 24 distinct `(series_id, observation_date)` pairs, one `collected_at` batch. So the specific risk of weekly re-collection silently duplicating rows does not occur under the current write pattern. The `QUALIFY` and this test exist as defense-in-depth against that write pattern changing in the future without `stg_fred_ppi` being revisited.

### 7.4 The series finding

`PCU42440042440012` — the series currently in use — is **"PPI by Industry: Grocery and Related Product Merchant Wholesalers: Wholesaling of Packaged Frozen and Canned Foods."** This is a **wholesale trade index measuring distributor gross margins on one packaged-food product line**, not an input-cost index. It is currently applied as a cost proxy across all 10 TrendShelf categories, and feeds `overall_margin_risk_score` at a 0.40 weight via `margin_pressure_proxy_score`.

The intended replacement is `PCU311311` (Food Manufacturing) — a producer-side cost index, not a wholesale-margin index. That switch is **not made in this commit or in commit `44afed8`**: `PCU311311` collection is added to the raw pipeline separately, and `scoring_ppi_series_id` stays pointed at `PCU42440042440012` until a deliberate later switch. The fix for the series-identity problem itself remains pending.

### 7.5 Standing rule

Check any FRED series' own page (title, breadcrumb category, units) before using it as an input to a model. FRED's breadcrumb path **"Industry Based > Wholesale Trade"** means the series measures trade margins, not the prices or costs a wholesale-trade series' name might suggest at a glance. This applies to every FRED series considered for TrendShelf going forward, not only PPI.

### 7.6 FRED now refreshes weekly

`collect_apis.py`'s FRED PPI block was moved out of the `if mode == "full":` gate to run in both modes, matching Kroger/SerpAPI — it now runs on the weekly `--mode prices` cron, not only during rare full-mode runs. `FRED_API_KEY` was added to `.github/workflows/weekly-collection.yml`'s collect-job `env:` block so the CI run can actually authenticate. Google Trends and BLS CPI remain full-mode-only, unchanged.

Before this, FRED had been collected exactly once (a manual full-mode pull) and never refreshed by CI, so `stg_fred_ppi` sat stuck at April 2026 while FRED itself had already published June. The **"2-month reporting lag"** documented in `fact_market_signals.sql`'s header and handled by the `fred_as_of` latest-available-as-of join is a real, permanent property of FRED's publishing schedule — it does not go away. What does go away with this change is the *second*, unrelated lag that had been stacking on top of it: TrendShelf simply never asking FRED for new data. Going forward, `stg_fred_ppi` should track FRED's own publishing lag only, not a multi-month collection gap on top of it.
